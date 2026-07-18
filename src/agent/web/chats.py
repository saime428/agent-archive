from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent.config import load_config
from agent.core.chat import ChatSession, ConversationState
from agent.core.run_store import RunStore, RunStoreError
from agent.llm.factory import make_llm
from agent.secrets import load_workspace_secrets
from agent.web.runs import build_run_replay


def build_chats_payload(workspace: Path, *, limit: int = 30) -> dict[str, Any]:
    root = workspace.resolve()
    states = ConversationState.list(root)
    states.sort(key=lambda item: item.updated_at, reverse=True)
    return {
        "workspace": str(root),
        "chats": [_chat_list_item(state) for state in states[:limit]],
    }


def build_chat_payload(workspace: Path, session_id: str) -> dict[str, Any]:
    root = workspace.resolve()
    state = ConversationState.load(root, session_id)
    return {
        "session_id": state.session_id,
        "title": _chat_title(state),
        "created_at": state.created_at,
        "updated_at": state.updated_at,
        "turn_count": len(state.turns),
        "turns": [_chat_turn_item(root, turn) for turn in state.turns],
    }


def _chat_list_item(state: ConversationState) -> dict[str, Any]:
    latest = state.turns[-1] if state.turns else None
    return {
        "session_id": state.session_id,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
        "turn_count": len(state.turns),
        "title": _chat_title(state),
        "latest_user": latest.user if latest else "",
        "latest_final": latest.final if latest else "",
        "status": latest.status if latest else "empty",
    }


def _chat_title(state: ConversationState) -> str:
    if state.title:
        return state.title
    for turn in state.turns:
        title = _compact_title(turn.user)
        if title:
            return title
    return "New chat"


def _compact_title(text: str, *, max_chars: int = 48) -> str:
    value = " ".join(str(text).split())
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def _chat_turn_item(workspace: Path, turn: Any) -> dict[str, Any]:
    item = asdict(turn)
    item["last_observation_summary"] = _friendly_observation_summary(str(item.get("last_observation_summary") or ""))
    item["process"] = _turn_process(workspace, turn)
    item["thinking_text"] = _turn_thinking_text(workspace, turn)
    return item


def build_chat_turn_payload(
    workspace: Path,
    request: dict[str, Any],
    *,
    mcp_runtime: Any | None = None,
) -> dict[str, Any]:
    message = request.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message is required.")
    session_id = request.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        raise ValueError("session_id must be a string.")
    approve_once = request.get("approve_once", False)
    if not isinstance(approve_once, bool):
        raise ValueError("approve_once must be a boolean.")

    root = workspace.resolve()
    load_workspace_secrets(root)
    config, diagnostics = load_config(root)
    state = load_or_create_chat_state(root, session_id)
    session = ChatSession(
        cwd=root,
        llm=make_llm(config),
        config=config,
        state=state,
        mcp_runtime=mcp_runtime,
    )
    result = session.run_turn(message.strip(), approval_handler=_approve_once_handler() if approve_once else None)
    return build_chat_turn_response(root, session, result, diagnostics)


def build_chat_rename_payload(workspace: Path, request: dict[str, Any]) -> dict[str, Any]:
    session_id = request.get("session_id")
    title = request.get("title")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session_id is required.")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required.")
    root = workspace.resolve()
    load_workspace_secrets(root)
    config, _diagnostics = load_config(root)
    state = ConversationState.load(root, session_id)
    state.title = _compact_title(title.strip(), max_chars=80)
    state.save(config)
    return {"status": "ok", "session_id": state.session_id, "title": state.title}


def build_chat_delete_payload(workspace: Path, request: dict[str, Any]) -> dict[str, Any]:
    session_id = request.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session_id is required.")
    root = workspace.resolve()
    ConversationState.delete(root, session_id)
    return {"status": "ok", "session_id": session_id, "deleted": True}


def build_chat_turn_response(root: Path, session: ChatSession, result: Any, diagnostics: Any) -> dict[str, Any]:
    turn = session.state.turns[-1]
    error = result.observation.error
    error_code = str(error.code) if error is not None else None
    repair_count = _repair_count(result.observations)
    return {
        "session_id": session.state.session_id,
        "title": _chat_title(session.state),
        "turn_count": len(session.state.turns),
        "run_id": turn.run_id,
        "status": turn.status,
        "completed": turn.completed,
        "display_status": _display_status(turn.completed, error_code, turn.status, turn.terminal_reason),
        "terminal_reason": turn.terminal_reason,
        "final": turn.final,
        "last_action": turn.last_action,
        "last_observation_summary": _friendly_observation_summary(turn.last_observation_summary),
        "summary_path": str(result.summary_path),
        "error_code": error_code,
        "error_message": error.message if error is not None else None,
        "approval_required": error_code == "APPROVAL_REQUIRED",
        "requested_action": result.action.action.name,
        "config_warnings": diagnostics.warnings,
        "repair_count": repair_count,
        "has_repair_noise": repair_count > 0,
        "process": _turn_process(root, turn),
        "thinking_text": _turn_thinking_text(root, turn),
    }


def load_or_create_chat_state(root: Path, session_id: str | None) -> ConversationState:
    if session_id:
        try:
            return ConversationState.load(root, session_id)
        except FileNotFoundError:
            return ConversationState.create(root, session_id=session_id)
    return ConversationState.create(root)


def _repair_count(observations: list[Any]) -> int:
    count = 0
    for observation in observations[:-1]:
        error = getattr(observation, "error", None)
        details = getattr(error, "details", None)
        if isinstance(details, dict) and "repair_attempt" in details:
            count += 1
    return count


def _display_status(completed: bool, error_code: str | None, status: str, terminal_reason: str) -> str:
    if completed:
        return "completed"
    if terminal_reason == "ask_user":
        return "ask_user"
    if error_code == "APPROVAL_REQUIRED":
        return "approval_required"
    if status == "error":
        return "error"
    return status


def _friendly_observation_summary(summary: str) -> str:
    messages = {
        (
            "Run commands execute local processes with the agent's OS permissions; "
            "workspace path checks do not fully contain file, network, or subprocess access. Approval is required."
        ): (
            "运行命令会以 Agent 当前的操作系统权限启动本地进程；"
            "工作区路径检查无法完整限制文件、网络或子进程访问。执行前需要你的批准。"
        ),
        "Action requires approval before execution.": "这个操作需要你先在右侧审查里批准。",
        "Action requires approval.": "这个操作需要你先批准。",
        "Approval required.": "需要审批。",
        "Web search is disabled. Enable it in Settings before searching the internet.": "联网搜索已关闭，请在设置里打开后再搜索网络。",
        "Path resolves outside the workspace.": "当前只允许读取工作区文件；如需查看电脑上的绝对路径，请先在设置里开启“读取电脑文件（只读）”。",
    }
    return messages.get(summary, summary)


def _turn_process(workspace: Path, turn: Any) -> list[str]:
    try:
        detail = RunStore(workspace.resolve()).show_run(turn.run_id)
    except RunStoreError:
        return _fallback_turn_process(turn)

    steps = build_run_replay(detail.tool_calls).get("steps", [])
    process: list[str] = []
    for step in steps[:6]:
        action = str(step.get("action") or "unknown")
        status = str(step.get("status") or "unknown")
        summary = str(step.get("summary") or "").strip()
        if action == "done":
            process.append("整理最终回答。")
        elif action == "ask_user":
            process.append(f"需要用户补充：{summary}")
        elif status == "error":
            process.append(f"{action} 遇到问题：{summary}")
        else:
            process.append(f"执行 {action}：{summary}")
    return process or _fallback_turn_process(turn)


def _turn_thinking_text(workspace: Path, turn: Any) -> str:
    try:
        detail = RunStore(workspace.resolve()).show_run(turn.run_id)
    except RunStoreError:
        return _fallback_thinking_text(turn)

    lines = [_thinking_line_from_tool_call(call) for call in detail.tool_calls]
    lines = [line for line in lines if line]
    if not lines:
        return _fallback_thinking_text(turn)
    return "我根据本轮运行记录整理了可公开的工作过程：\n" + "\n".join(f"- {line}" for line in lines[:8])


def _thinking_line_from_tool_call(call: Any) -> str:
    if not call.valid or not call.data:
        return "有一条运行记录无法解析，已跳过并继续查看后续结果。"

    action = call.data.get("action")
    inner_action = action.get("action") if isinstance(action, dict) else None
    observation = call.data.get("observation")
    action_name = str(inner_action.get("name") or "unknown") if isinstance(inner_action, dict) else "unknown"
    args = inner_action.get("args") if isinstance(inner_action, dict) and isinstance(inner_action.get("args"), dict) else {}
    status = str(observation.get("status") or "unknown") if isinstance(observation, dict) else "unknown"
    intent = _public_action_message(action)

    if action_name == "invalid_model_response":
        return ""
    if action_name == "done":
        return f"{intent} - 整理最终回答。" if intent else "整理最终回答。"
    if action_name == "ask_user":
        line = "需要你补充信息后再继续。"
        return f"{intent} - {line}" if intent else line

    label = _thinking_action_label(action_name)
    target = _thinking_target(args)
    if status == "error":
        error = observation.get("error") if isinstance(observation, dict) else None
        error_code = str(error.get("code") or "") if isinstance(error, dict) else ""
        if error_code == "APPROVAL_REQUIRED":
            line = f"{label}{target}需要你批准后才会执行。"
        else:
            line = f"{label}{target}没有完成，详情已放到右侧审查。"
    else:
        line = f"{label}{target}。"
    return f"{intent} - {line}" if intent else line


def _public_action_message(action: Any) -> str:
    if not isinstance(action, dict):
        return ""
    message = " ".join(str(action.get("message") or "").split())
    if len(message) <= 120:
        return message
    return message[:117].rstrip() + "..."


def _thinking_action_label(action_name: str) -> str:
    labels = {
        "list_dir": "列出目录",
        "read_file": "读取文件",
        "search_files": "搜索文件",
        "web_search": "联网搜索",
        "write_file": "保存文件",
        "apply_patch": "应用补丁",
        "run_command": "运行命令",
        "git_status": "查看 Git 状态",
        "git_diff": "查看 Git 差异",
        "read_pdf": "读取 PDF",
        "read_docx": "读取 DOCX",
        "read_xlsx": "读取 XLSX",
        "read_pptx": "读取 PPTX",
        "write_markdown_report": "写入 Markdown 报告",
    }
    return labels.get(action_name, "执行工具")


def _thinking_target(args: dict[str, Any]) -> str:
    value = args.get("path") or args.get("query")
    if not value and isinstance(args.get("argv"), list):
        value = " ".join(str(item) for item in args["argv"][:4])
    if not value:
        return ""
    value = str(value)
    if len(value) > 80:
        value = value[:77] + "..."
    return f" `{value}`"


def _fallback_thinking_text(turn: Any) -> str:
    action = str(getattr(turn, "last_action", "") or "")
    if action == "done":
        return "我根据本轮运行记录整理了可公开的工作过程：\n- 整理最终回答。"
    if action == "ask_user":
        return "我根据本轮运行记录整理了可公开的工作过程：\n- 需要你补充信息后再继续。"
    return "我根据本轮运行记录整理了可公开的工作过程：\n- 已完成本轮处理，详情可在右侧审查查看。"


def _fallback_turn_process(turn: Any) -> list[str]:
    action = str(getattr(turn, "last_action", "") or "unknown")
    summary = str(getattr(turn, "last_observation_summary", "") or "").strip()
    if not summary:
        return ["已完成本轮处理。"]
    return [f"执行 {action}：{summary}"]


def _approve_once_handler():
    approved = False

    def approve_once(_action: Any) -> bool:
        nonlocal approved
        if approved:
            return False
        approved = True
        return True

    return approve_once
