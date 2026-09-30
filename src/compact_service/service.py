"""
Compact service for /compact command.

Handles the full compaction flow:
1. Pre-process messages (microcompact, strip images)
2. Call LLM to generate summary
3. Return boundary marker + summary messages
4. Update conversation in place
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from ..agent.conversation import Conversation, Message
from ..context_system.microcompact import microcompact_messages, strip_images_from_messages
from ..providers.base import Provider, stream_with_retry
from ..providers.convert import to_canonical
from .messages import (
    create_compact_boundary_message,
    create_compact_summary_message,
    get_messages_after_boundary,
    is_compact_boundary_message,
)

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM_PROMPT = "You summarize coding conversations accurately and concisely."


def _has_tool_result(api_message: dict[str, Any]) -> bool:
    content = api_message.get("content")
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )



# No-tools preamble prepended to the summary prompt
NO_TOOLS_PREAMBLE = """CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.
Do NOT use Read, Bash, Grep, or any other tool. Your entire response must be plain text.
"""

SUMMARY_PROMPT_TEMPLATE = NO_TOOLS_PREAMBLE + """
Your task is to create a detailed summary of the conversation so far.

Include:
1. Primary Request and Intent: What the user asked for
2. Key Technical Concepts: Technologies, frameworks, patterns discussed
3. Files and Code Sections: Files examined, modified, or created (with snippets)
4. Errors and Fixes: Problems encountered and how they were resolved
5. Problem Solving: What was accomplished
6. All User Messages: All non-tool-result user messages
7. Pending Tasks: Tasks explicitly requested but not yet done
8. Current Work: What was being worked on immediately before this summary
9. Optional Next Step: Next step in line with recent requests

Respond ONLY with plain text. No tools. No XML tags.
"""


@dataclass
class CompactResult:
    """Result of a compaction operation."""
    boundary_message: Message
    summary_message: Message
    tokens_saved: int
    pre_compact_count: int
    post_compact_count: int
    summary_text: str
    trigger: str = "manual"
    user_display_message: Optional[str] = None


async def compact_conversation(
    conversation: Conversation,
    provider: Provider,
    model: str,
    custom_instructions: Optional[str] = None,
    trigger: str = "manual",
) -> CompactResult:
    """
    Compact a conversation by summarizing older messages.

    This is the Python equivalent of the TypeScript compactConversation().
    It is NOT a 1:1 port — it omits features unavailable in a Python CLI:
    - Forked agent with cache sharing (no subprocess isolation in Python REPL)
    - Session memory (no disk-backed session memory extraction)
    - Reactive compact (no background compaction agent)
    - Hook system (no pre/post compact hooks in ClydeCLI)

    Args:
        conversation: The live Conversation object (mutated in place)
        provider: The LLM provider for generating the summary
        model: Model name for the summary call
        custom_instructions: Optional user instructions for the summarizer
        trigger: "manual" or "auto"

    Returns:
        CompactResult with boundary, summary, and metadata
    """
    # Step 1: Get messages after the last boundary (skip already-summarized)
    messages = get_messages_after_boundary(conversation.messages)

    if len(messages) < 2:
        raise ValueError("Not enough messages to compact.")

    # Step 2: Count pre-compact tokens
    from ..context_system.token_estimation import count_messages_tokens
    api_messages = conversation.get_messages()
    pre_compact_tokens = count_messages_tokens(api_messages)
    pre_compact_count = len(conversation.messages)

    # Step 3: Microcompact — strip images and clear old tool results
    api_messages_stripped = strip_images_from_messages(api_messages)
    compacted_api, tokens_saved = microcompact_messages(api_messages_stripped)

    # Step 4: Build summary prompt
    prompt = SUMMARY_PROMPT_TEMPLATE
    if custom_instructions:
        prompt += f"\n\nAdditional instructions: {custom_instructions}"

    # Recent messages as context (after microcompact), bounded to stay within context
    # limits. Start at a plain user turn so the slice never opens on a tool result whose
    # tool call was cut off (providers reject that pairing).
    context_messages = list(compacted_api[-20:])
    while context_messages and (
        context_messages[0].get("role") != "user" or _has_tool_result(context_messages[0])
    ):
        context_messages.pop(0)
    summary_history = Conversation.from_dict(
        {"messages": [*context_messages, {"role": "user", "content": prompt}]}
    )

    # Step 5: Call the LLM to generate summary (no tools, reasoning off)
    summary_text = ""
    try:
        # Tool blocks are flattened to text: providers reject tool_use/tool_result blocks in a
        # request that defines no tools.
        response = stream_with_retry(
            provider,
            to_canonical(summary_history, SUMMARY_SYSTEM_PROMPT, flatten_tools=True),
            model,
            (),
            lambda _chunk: None,
            reasoning="off",
        )
        summary_text = (response.message.text or "").strip()
    except Exception as e:
        logger.warning(f"Compact LLM call failed: {e}, using text extraction")
        summary_text = _fallback_summary(messages)

    if not summary_text:
        summary_text = _fallback_summary(messages)

    # Step 6: Create boundary marker
    last_msg_uuid = None
    if messages:
        last_msg = messages[-1]
        if hasattr(last_msg, 'uuid'):
            last_msg_uuid = getattr(last_msg, 'uuid', None)
        elif isinstance(last_msg, dict):
            last_msg_uuid = last_msg.get("uuid")

    boundary_msg = create_compact_boundary_message(
        trigger=trigger,
        pre_compact_token_count=pre_compact_tokens,
        last_message_uuid=last_msg_uuid,
    )

    # Step 7: Create summary message
    summary_msg = create_compact_summary_message(summary_text)

    # Step 8: Insert boundary + summary into conversation
    # Find position after the last boundary marker
    boundary_indices = [
        i for i, m in enumerate(conversation.messages)
        if is_compact_boundary_message(m)
    ]

    if boundary_indices:
        insert_pos = max(boundary_indices) + 1
    else:
        insert_pos = 0

    # Remove messages that were summarized (everything from insert_pos onward)
    # Then insert boundary + summary
    if insert_pos == 0:
        # No existing boundary — clear all and start fresh
        conversation.messages.clear()
        conversation.messages.append(boundary_msg)
        conversation.messages.append(summary_msg)
    else:
        # Keep messages before boundary, then boundary + summary
        conversation.messages = list(conversation.messages[:insert_pos])
        conversation.messages.append(boundary_msg)
        conversation.messages.append(summary_msg)

    post_compact_count = len(conversation.messages)

    # Step 9: Build user display message
    saved_str = f"~{tokens_saved:,}" if tokens_saved > 0 else "some"
    user_display = (
        f"Compacted conversation ({saved_str} tokens saved). "
        f"Pre-compact: {pre_compact_tokens:,} tokens. "
        f"Press Ctrl+O to see full summary."
    )

    return CompactResult(
        boundary_message=boundary_msg,
        summary_message=summary_msg,
        tokens_saved=tokens_saved,
        pre_compact_count=pre_compact_count,
        post_compact_count=post_compact_count,
        summary_text=summary_text,
        trigger=trigger,
        user_display_message=user_display,
    )


def _fallback_summary(messages: list[Message]) -> str:
    """
    Generate a simple text fallback summary when the LLM call fails.
    """
    user_msgs: list[str] = []
    assistant_msgs: list[str] = []

    for msg in messages:
        role = getattr(msg, 'role', None)
        if role is None and isinstance(msg, dict):
            role = msg.get("role")

        content = getattr(msg, 'content', '')
        if content is None and isinstance(msg, dict):
            content = msg.get("content", "")

        if role == "user":
            if isinstance(content, str):
                user_msgs.append(content[:200])
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        user_msgs.append(block.get("text", "")[:200])
        elif role == "assistant":
            if isinstance(content, str):
                assistant_msgs.append(content[:200])
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        assistant_msgs.append(block.get("text", "")[:200])

    summary_parts = [f"Conversation had {len(messages)} messages."]

    # Extract tool use info
    tool_uses = []
    for msg in messages:
        content = getattr(msg, 'content', [])
        if isinstance(msg, dict):
            content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_uses.append(block.get("name", ""))

    if tool_uses:
        summary_parts.append(f"Tools used: {', '.join(tool_uses[:10])}")

    if user_msgs:
        summary_parts.append(f"Last user message: {user_msgs[-1][:150]}")
    if assistant_msgs:
        summary_parts.append(f"Last assistant message: {assistant_msgs[-1][:150]}")

    return "\n".join(summary_parts)
