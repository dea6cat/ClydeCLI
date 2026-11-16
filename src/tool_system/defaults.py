from __future__ import annotations

from src.config import clyde_home

from .loader import load_tools_from_dir
from .registry import ToolRegistry
from .tools import (
    DataTool,
    AskUserQuestionTool,
    BashTool,
    MapTool,
    RetrieveContextTool,
    RememberTool,
    ConfigTool,
    CronCreateTool,
    CronDeleteTool,
    CronListTool,
    EnterPlanModeTool,
    EnterWorktreeTool,
    ExitPlanModeTool,
    ExitWorktreeTool,
    FileEditTool,
    FileReadTool,
    FileWriteTool,
    GlobTool,
    GrepTool,
    LSPTool,
    ListMcpResourcesTool,
    MCPTool,
    NotebookEditTool,
    ReadMcpResourceTool,
    SendUserMessageTool,
    SkillTool,
    SleepTool,
    StructuredOutputTool,
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskOutputTool,
    TaskStopTool,
    TaskUpdateTool,
    TodoWriteTool,
    WebFetchTool,
    WebSearchTool,
)
from .tools.tool_search import ToolSearchTool


def build_default_registry(*, include_user_tools: bool = True) -> ToolRegistry:
    registry = ToolRegistry(
        tools=[
            SendUserMessageTool(),
            BashTool(),
            FileReadTool(),
            DataTool(),
            FileWriteTool(),
            FileEditTool(),
            GlobTool(),
            GrepTool(),
            WebFetchTool(),
            WebSearchTool(),
            SleepTool(),
            TaskStopTool(),
            ConfigTool(),
            MCPTool(),
            ListMcpResourcesTool(),
            ReadMcpResourceTool(),
            LSPTool(),
            SkillTool(),
            AskUserQuestionTool(),
            TodoWriteTool(),
            TaskCreateTool(),
            TaskGetTool(),
            TaskListTool(),
            TaskUpdateTool(),
            TaskOutputTool(),
            EnterPlanModeTool(),
            ExitPlanModeTool(),
            EnterWorktreeTool(),
            ExitWorktreeTool(),
            CronCreateTool(),
            CronListTool(),
            CronDeleteTool(),
            StructuredOutputTool(),
            NotebookEditTool(),
            MapTool(),
            RetrieveContextTool(),
            RememberTool(),
        ]
    )
    registry.register(ToolSearchTool(registry))

    if include_user_tools:
        user_dir = clyde_home() / "tools"
        for tool in load_tools_from_dir(user_dir):
            registry.register(tool)

    return registry
