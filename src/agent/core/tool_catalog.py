from __future__ import annotations

from dataclasses import dataclass

from agent.policy.approvals import CONFIRMATION_REQUIRED_ACTIONS, LOW_RISK_ACTIONS


@dataclass(frozen=True)
class ToolInfo:
    name: str
    category: str
    dry_run: str
    description: str


TOOL_DESCRIPTIONS = {
    "done": "Finish the run with a final response.",
    "ask_user": "Stop and return a structured user question.",
    "list_dir": "List workspace directory entries.",
    "read_file": "Read a workspace text file.",
    "read_pdf": "Extract text from a workspace PDF as untrusted source material.",
    "read_docx": "Extract text from a workspace DOCX as untrusted source material.",
    "read_xlsx": "Extract sheet summaries from a workspace XLSX as untrusted source material.",
    "read_pptx": "Extract slide text from a workspace PPTX as untrusted source material.",
    "write_markdown_report": "Write a source-grounded Markdown report with snapshot protection.",
    "search_files": "Search workspace paths and text.",
    "web_search": "Search the public web when enabled in Settings.",
    "write_file": "Write a workspace text file with snapshot protection.",
    "apply_patch": "Apply structured text replacements with snapshots.",
    "run_command": "Run an allowed structured argv command.",
    "git_status": "Show repository status.",
    "git_diff": "Show repository diff.",
}

DRY_RUN_SKIPPED_TOOLS = {"write_file", "apply_patch", "run_command", "write_markdown_report"}


def list_tool_infos() -> list[ToolInfo]:
    return [
        ToolInfo(
            name=name,
            category=tool_category(name),
            dry_run="skipped" if name in DRY_RUN_SKIPPED_TOOLS else "executes",
            description=description,
        )
        for name, description in TOOL_DESCRIPTIONS.items()
    ]


def tool_category(tool_name: str) -> str:
    if tool_name in {"done", "ask_user"}:
        return "terminal"
    if tool_name in LOW_RISK_ACTIONS:
        return "low-risk"
    if tool_name in CONFIRMATION_REQUIRED_ACTIONS:
        return "confirmation-required"
    return "unknown"
