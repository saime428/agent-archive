from __future__ import annotations

from collections.abc import Iterable

from agent.core.actions import ARGS_MODELS

ACTION_DESCRIPTIONS: dict[str, str] = {
    "done": "Finish the task and return the final user-facing answer.",
    "ask_user": "Ask the user a clarifying question when you cannot proceed.",
    "list_dir": "List entries in a directory.",
    "read_file": "Read a text file, optionally from a start line with a line limit.",
    "search_files": "Search file contents in the workspace for a query string.",
    "web_search": "Search the web for current information.",
    "write_file": "Create or overwrite a text file with the given content.",
    "apply_patch": "Apply one or more exact string-replacement edits to files.",
    "run_command": "Run an allowed command without a shell.",
    "git_status": "Show git status for the workspace.",
    "git_diff": "Show a git diff, optionally for one path or the staged index.",
    "read_pdf": "Extract text from a PDF file.",
    "read_docx": "Extract text from a Word document.",
    "read_xlsx": "Extract text from an Excel workbook.",
    "read_pptx": "Extract text from a PowerPoint file.",
    "write_markdown_report": "Write a Markdown report file with title, body, and sources.",
}

_TERMINAL_ACTIONS = ("done", "ask_user")


def native_tool_names(*, web_search_enabled: bool) -> list[str]:
    names = list(_TERMINAL_ACTIONS)
    for name in sorted(set(ARGS_MODELS) - set(_TERMINAL_ACTIONS)):
        if name == "web_search" and not web_search_enabled:
            continue
        names.append(name)
    return names


def build_tool_schemas(action_names: Iterable[str]) -> list[dict]:
    schemas: list[dict] = []
    for name in action_names:
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": ACTION_DESCRIPTIONS.get(name, ""),
                    "parameters": ARGS_MODELS[name].model_json_schema(),
                },
            }
        )
    return schemas
