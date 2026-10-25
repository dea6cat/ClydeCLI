"""Plain answers to a permission question: "sure, go ahead" allows; "no, edit the copy in src/ instead" holds the action and tells Clyde why.

When the user answers a permission prompt in their own words instead of a listed key, a model reads the words in a tool-free call of
its own and says whether they are a plain, unconditional yes. It sees only the reply, never the question: the question quotes the
action asking to run, which must not get a say in its own approval. A model that can't be reached, takes longer than TIMEOUT_S, or
answers anything but YES, is a no; the caller then denies that exact action and hands the reply to the model as the user's words.
"""

from __future__ import annotations

import threading
from typing import Any

YES_CHECK = ("You read one chat reply and decide whether it is a plain, unconditional yes: agreement to go ahead exactly as "
             "asked, in any language or wording (\"yes\", \"sure\", \"go ahead\", \"dale\", \"ok\"). Answer with one word: "
             "YES for that, OTHER for anything else: a no, a yes with a condition, change or extra request (\"yes but only "
             "the old ones\"), a question, or anything unclear.")
TIMEOUT_S = 15   # slower than this counts as no: the user is waiting, and nothing runs on a guess


def judge(repl: Any) -> tuple[Any, str]:
    """The model to ask: the session's own, except that under cardShuffle it is the real model dealt last, which has just
    answered; cardShuffle's own deal can spend minutes on providers that fail before one answers."""
    from src.providers.registry import resolve
    dealt = getattr(repl.provider, "dealt", None)
    found = resolve(repl.registry, dealt) if isinstance(dealt, str) and getattr(repl, "registry", None) else None
    return found or (repl.provider, repl.model)


def is_plain_yes(provider: Any, model: str, reply: str) -> tuple[bool, str]:
    """(whether `reply` is a plain yes, why not when no verdict came: "" when the model answered)."""
    from src.agent.conversation import Conversation
    from src.providers.base import stream_with_retry
    from src.providers.convert import to_canonical
    history = Conversation()
    history.add_user_message(f"Reply: {reply}")
    request, cancel, result = to_canonical(history, YES_CHECK), threading.Event(), {}

    def ask() -> None:
        try:
            result["text"] = stream_with_retry(provider, request, model, (), lambda _chunk: None, reasoning="off",
                                               cancel=cancel).message.text or ""
        except Exception as e:  # pylint: disable=broad-exception-caught
            result["error"] = e

    worker = threading.Thread(target=ask, name="plain-answer-check", daemon=True)
    worker.start()
    worker.join(TIMEOUT_S)
    if worker.is_alive():
        cancel.set()   # aborts the request; its late answer is ignored
        return False, f"no verdict on your answer within {TIMEOUT_S}s"
    if "error" in result:
        return False, f"couldn't read your answer ({result['error']})"
    answer = result["text"].rsplit("</think>", 1)[-1]   # a thinking model may still write its reasoning first
    return answer.strip().strip(".!").upper() == "YES", ""
