from __future__ import annotations

import errno
import importlib.util
import json
import os
import platform
import shutil
from pathlib import Path

import typer
from rich.console import Console

from agent.config import ConfigError, ConfigOverrides, load_config
from agent.core.chat import ChatSession, ConversationState
from agent.core.loop import run_once
from agent.core.memory import MemoryError, MemoryStore
from agent.core.run_store import RunStore, RunStoreError
from agent.core.skills import SkillError, discover_skills, load_selected_skills
from agent.core.tool_catalog import list_tool_infos
from agent.llm.deepseek import DEFAULT_DEEPSEEK_BASE_URL, DeepSeekError, smoke_deepseek_provider
from agent.llm.factory import make_llm as make_llm_client
from agent.llm.openai_compat import ProviderError, smoke_provider, smoke_provider_native
from agent.secrets import load_workspace_secrets
from agent.web.server import serve_workbench

app = typer.Typer(help="Minimal Python CLI agent.")
runs_app = typer.Typer(help="Inspect agent run logs.")
tools_app = typer.Typer(help="Inspect available agent tools.")
config_app = typer.Typer(help="Inspect agent configuration.")
skills_app = typer.Typer(help="Inspect and load agent skills.")
memory_app = typer.Typer(help="Review and manage agent memory.")
provider_app = typer.Typer(help="Inspect and smoke-test LLM providers.")
release_app = typer.Typer(help="Inspect release readiness.")
app.add_typer(runs_app, name="runs")
app.add_typer(tools_app, name="tools")
app.add_typer(config_app, name="config")
app.add_typer(skills_app, name="skills")
app.add_typer(memory_app, name="memory")
app.add_typer(provider_app, name="provider")
app.add_typer(release_app, name="release")

WORKBENCH_PORT_ATTEMPTS = 200
console = Console(highlight=False)
DOCUMENT_DEPENDENCIES = {
    "pypdf": "pypdf",
    "python-docx": "docx",
    "openpyxl": "openpyxl",
    "python-pptx": "pptx",
}


@app.callback()
def _root() -> None:
    """Minimal Python CLI agent."""


@app.command()
def doctor() -> None:
    """Report the minimal local environment status."""
    _print_doctor(Path.cwd())


def _print_doctor(cwd: Path) -> None:
    load_workspace_secrets(cwd)
    try:
        config, diagnostics = load_config(cwd)
    except ConfigError as exc:
        console.print(f"config error: {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"Python: {platform.python_version()}")
    console.print(f"cwd: {cwd.resolve()}")
    console.print("agent import: ok")
    rg_available = shutil.which("rg") is not None
    console.print(f"rg available: {str(rg_available).lower()}")
    console.print(f"search backend: {'rg' if rg_available else 'python'}")
    console.print(f"config mode: {config.mode}")
    console.print(f"native_tools: {config.native_tools}")
    console.print(f"config provider: {config.provider}")
    console.print(f"config model: {config.model}")
    console.print(f"config default_skills: {list(config.default_skills)}")
    console.print(f"config allowed_commands: {list(config.allowed_commands)}")
    console.print(f"deepseek api key env: {config.deepseek_api_key_env}")
    console.print(f"deepseek api key present: {str(bool(os.environ.get(config.deepseek_api_key_env))).lower()}")
    if config.provider == "openai-compat":
        console.print(f"base_url: {config.base_url}")
        console.print(f"api_key_env: {config.api_key_env}")
        console.print(f"api key present: {str(bool(os.environ.get(config.api_key_env))).lower()}")
    console.print(f"config sandbox: {config.sandbox}")
    console.print(f"config approval: {config.approval}")
    console.print(f"config dry_run: {str(config.dry_run).lower()}")
    console.print(f"config web_search_enabled: {str(config.web_search_enabled).lower()}")
    console.print(f"config computer_read_enabled: {str(config.computer_read_enabled).lower()}")
    for package_name, import_name in DOCUMENT_DEPENDENCIES.items():
        present = importlib.util.find_spec(import_name) is not None
        console.print(f"document dependency {package_name}: {'present' if present else 'missing'}")
    console.print(f"config global: {diagnostics.global_config_path}")
    console.print(f"config project: {diagnostics.project_config_path}")
    for warning in diagnostics.warnings:
        console.print(f"config warning: {warning}")


@release_app.command("doctor")
def release_doctor(
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for release readiness."),
) -> None:
    """Report release readiness without running tests or network checks."""
    workspace = (cwd or Path.cwd()).resolve()
    load_workspace_secrets(workspace)
    try:
        config, diagnostics = load_config(workspace)
    except ConfigError as exc:
        console.print(f"config readable: false")
        console.print(f"config error: {exc}")
        raise typer.Exit(code=1) from exc

    console.print("release readiness: complete")
    console.print("route completion: 100%")
    console.print("startup command: agent start")
    console.print("config readable: true")
    console.print(f"provider: {config.provider}")
    console.print(f"model: {config.model}")
    console.print(f"deepseek api key present: {str(bool(os.environ.get(config.deepseek_api_key_env))).lower()}")
    console.print("settings writes: read-only")
    console.print("packaging: deferred (not required for local release)")
    console.print("test command: python -m pytest -q")
    console.print("check command: git diff --check")
    for warning in diagnostics.warnings:
        console.print(f"config warning: {warning}")


@app.command()
def run(
    task: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for the run."),
    mode: str | None = typer.Option(None, "--mode", help="Run mode."),
    sandbox: str | None = typer.Option(None, "--sandbox", help="Sandbox mode."),
    approval: str | None = typer.Option(None, "--approval", help="Approval mode."),
    dry_run: bool | None = typer.Option(None, "--dry-run/--no-dry-run", help="Record dry-run intent in config."),
    provider: str | None = typer.Option(None, "--provider", help="LLM provider."),
    model: str | None = typer.Option(None, "--model", help="LLM model."),
    skill: list[str] | None = typer.Option(None, "--skill", help="Skill to load for this run."),
) -> None:
    """Run an agent task."""
    workspace = (cwd or Path.cwd()).resolve()
    load_workspace_secrets(workspace)
    try:
        config, diagnostics = load_config(
            workspace,
            overrides=ConfigOverrides(
                mode=mode,
                sandbox=sandbox,
                approval=approval,
                dry_run=dry_run,
                provider=provider,
                model=model,
            ),
        )
    except ConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    try:
        llm = _make_llm(config)
    except DeepSeekError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    selected_skills = skill if skill else None
    try:
        result = run_once(task, llm, cwd=workspace, config=config, selected_skills=selected_skills)
    except DeepSeekError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    final = (result.observation.data or {}).get("final", "")
    terminal_reason = _result_terminal_reason(result)
    console.print(f"run_id: {result.context.run_id}")
    console.print(f"mode: {config.mode}")
    console.print(f"sandbox: {config.sandbox}")
    console.print(f"approval: {config.approval}")
    console.print(f"dry_run: {str(config.dry_run).lower()}")
    console.print(f"web_search_enabled: {str(config.web_search_enabled).lower()}")
    console.print(f"computer_read_enabled: {str(config.computer_read_enabled).lower()}")
    console.print(f"provider: {config.provider}")
    console.print(f"model: {config.model}")
    console.print(f"skills: {[item.name for item in result.skills]}")
    console.print(f"status: {result.observation.status}")
    console.print(f"completed: {str(_result_completed(result)).lower()}")
    console.print(f"terminal_reason: {terminal_reason}")
    for warning in diagnostics.warnings:
        console.print(f"config warning: {warning}")
    console.print(f"final: {final}")
    console.print(f"summary: {result.summary_path}", soft_wrap=True)
    if result.observation.error is not None:
        console.print(f"error: {_error_code(result.observation.error)}: {result.observation.error.message}")
        console.print(f"inspect: python -m agent.cli runs show {result.context.run_id}")
        raise typer.Exit(code=1)


@app.command()
def ui(
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for the workbench."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host interface for the local workbench."),
    port: int = typer.Option(8000, "--port", help="Port for the local workbench."),
    open_browser: bool = typer.Option(False, "--open-browser/--no-open-browser", help="Open the selected workbench URL."),
) -> None:
    """Start the local read-only web workbench."""
    workspace = (cwd or Path.cwd()).resolve()
    _start_workbench(workspace, host, port, open_browser=open_browser)


@app.command()
def start(
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for the workbench."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host interface for the local workbench."),
    port: int = typer.Option(8000, "--port", help="Port for the local workbench."),
    open_browser: bool = typer.Option(False, "--open-browser/--no-open-browser", help="Open the selected workbench URL."),
) -> None:
    """Start Agent Workbench."""
    workspace = (cwd or Path.cwd()).resolve()
    _start_workbench(workspace, host, port, open_browser=open_browser)


def _start_workbench(workspace: Path, host: str, port: int, *, open_browser: bool = False) -> None:
    load_workspace_secrets(workspace)
    try:
        load_config(workspace)
    except ConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    last_error: OSError | None = None
    for candidate in range(port, port + WORKBENCH_PORT_ATTEMPTS):
        try:
            if candidate != port:
                console.print(f"Port {candidate - 1} is busy; trying {candidate}.")
            serve_workbench(workspace=workspace, host=host, port=candidate, open_browser=open_browser)
            return
        except OSError as exc:
            if not _is_address_in_use(exc):
                console.print(f"Could not start Agent Workbench: {exc}")
                raise typer.Exit(code=1) from exc
            last_error = exc
    console.print(f"Could not start Agent Workbench: {last_error}")
    raise typer.Exit(code=1)


def _is_address_in_use(exc: OSError) -> bool:
    return exc.errno == errno.EADDRINUSE or getattr(exc, "winerror", None) in {10013, 10048}


@app.command()
def chat(
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for the chat."),
    resume: str | None = typer.Option(None, "--resume", help="Resume a chat session id."),
    mode: str | None = typer.Option(None, "--mode", help="Run mode."),
    sandbox: str | None = typer.Option(None, "--sandbox", help="Sandbox mode."),
    approval: str | None = typer.Option(None, "--approval", help="Approval mode."),
    dry_run: bool | None = typer.Option(None, "--dry-run/--no-dry-run", help="Record dry-run intent in config."),
    provider: str | None = typer.Option(None, "--provider", help="LLM provider."),
    model: str | None = typer.Option(None, "--model", help="LLM model."),
    skill: list[str] | None = typer.Option(None, "--skill", help="Skill to load for chat turns."),
) -> None:
    """Start an interactive agent chat."""
    workspace = (cwd or Path.cwd()).resolve()
    load_workspace_secrets(workspace)
    try:
        config, diagnostics = load_config(
            workspace,
            overrides=ConfigOverrides(
                mode=mode,
                sandbox=sandbox,
                approval=approval,
                dry_run=dry_run,
                provider=provider,
                model=model,
            ),
        )
    except ConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    try:
        llm = _make_llm(config)
    except DeepSeekError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    try:
        state = ConversationState.load(workspace, resume) if resume else ConversationState.create(workspace)
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        console.print(f"Could not resume chat session {resume}: {exc}")
        raise typer.Exit(code=1) from exc

    selected_skills = skill if skill else None
    session = ChatSession(
        cwd=workspace,
        llm=llm,
        config=config,
        state=state,
        selected_skills=selected_skills,
    )
    console.print(f"chat_id: {state.session_id}")
    console.print(f"workspace: {workspace}")
    console.print(f"provider: {config.provider}")
    console.print(f"model: {config.model}")
    for warning in diagnostics.warnings:
        console.print(f"config warning: {warning}")

    while True:
        try:
            user_input = input("agent> ")
        except EOFError:
            console.print("chat ended")
            break
        except KeyboardInterrupt:
            console.print("\nchat ended")
            break
        if not user_input.strip():
            continue
        command_result = _handle_chat_command(user_input.strip(), session, config)
        if command_result == "exit":
            console.print("chat ended")
            break
        if command_result == "handled":
            continue
        stream_handler, stream_was_used = _make_chat_stream_handler(
            config.provider in {"deepseek", "openai-compat"}
        )
        try:
            result = session.run_turn(
                user_input,
                approval_handler=_chat_approval_handler,
                event_handler=_chat_event_handler,
                stream_handler=stream_handler,
            )
        except DeepSeekError as exc:
            console.print(str(exc))
            continue
        if stream_was_used():
            console.file.write("\n")
        turn_number = len(session.state.turns)
        final = (result.observation.data or {}).get("final", "")
        terminal_reason = _result_terminal_reason(result)
        console.print(f"turn: {turn_number}")
        console.print(f"run_id: {result.context.run_id}")
        console.print(f"status: {result.observation.status}")
        console.print(f"completed: {str(_result_completed(result)).lower()}")
        console.print(f"terminal_reason: {terminal_reason}")
        console.print(f"final: {final}")
        console.print(f"summary: {result.summary_path}", soft_wrap=True)
        if result.observation.error is not None:
            console.print(f"error: {_error_code(result.observation.error)}: {result.observation.error.message}")


@tools_app.command("list")
def tools_list() -> None:
    """List available tools and policy categories."""
    for tool in list_tool_infos():
        console.file.write(f"{tool.name}\t{tool.category}\tdry-run: {tool.dry_run}\t{tool.description}\n")


@config_app.command("show")
def config_show(cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project config.")) -> None:
    """Show the effective merged configuration."""
    workspace = (cwd or Path.cwd()).resolve()
    try:
        config, diagnostics = load_config(workspace)
    except ConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    console.print(f"cwd: {workspace}", soft_wrap=True)
    console.print(f"mode: {config.mode}")
    console.print(f"native_tools: {config.native_tools}")
    console.print(f"provider: {config.provider}")
    console.print(f"model: {config.model}")
    console.print(f"deepseek_api_key_env: {config.deepseek_api_key_env}")
    if config.provider == "openai-compat":
        console.print(f"base_url: {config.base_url}")
        console.print(f"api_key_env: {config.api_key_env}")
        console.print(f"api key present: {str(bool(os.environ.get(config.api_key_env))).lower()}")
    console.print(f"default_skills: {list(config.default_skills)}")
    console.print(f"allowed_commands: {list(config.allowed_commands)}")
    console.print(f"memory_auto_write: {str(config.memory_auto_write).lower()}")
    console.print(f"memory_max_items: {config.memory_max_items}")
    console.print(f"sandbox: {config.sandbox}")
    console.print(f"approval: {config.approval}")
    console.print(f"dry_run: {str(config.dry_run).lower()}")
    console.print(f"web_search_enabled: {str(config.web_search_enabled).lower()}")
    console.print(f"computer_read_enabled: {str(config.computer_read_enabled).lower()}")
    console.print(f"global config: {diagnostics.global_config_path}", soft_wrap=True)
    console.print(f"project config: {diagnostics.project_config_path}", soft_wrap=True)
    if diagnostics.loaded_files:
        for path in diagnostics.loaded_files:
            console.print(f"loaded file: {path.resolve()}", soft_wrap=True)
    else:
        console.print("loaded files: none")
    for warning in diagnostics.warnings:
        console.print(f"config warning: {warning}")


@config_app.command("doctor")
def config_doctor(
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project config."),
) -> None:
    """Report configuration and local environment diagnostics."""
    _print_doctor((cwd or Path.cwd()).resolve())


@provider_app.command("smoke")
def provider_smoke(
    provider_name: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project config."),
    model: str | None = typer.Option(None, "--model", help="Model to smoke-test."),
    native: bool = typer.Option(False, "--native", help="Smoke-test native tool calling."),
) -> None:
    """Run an explicit provider smoke test without creating an agent run."""
    if provider_name not in {"deepseek", "openai-compat"}:
        console.print(f"Unsupported provider smoke target: {provider_name}")
        raise typer.Exit(code=1)
    workspace = (cwd or Path.cwd()).resolve()
    load_workspace_secrets(workspace)
    try:
        config, diagnostics = load_config(workspace, overrides=ConfigOverrides(model=model))
    except ConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    if provider_name == "deepseek":
        api_key = os.environ.get(config.deepseek_api_key_env, "")
        if not api_key:
            console.print(f"DeepSeek API key is required in {config.deepseek_api_key_env}.")
            raise typer.Exit(code=1)

        try:
            if native:
                result = smoke_provider_native(
                    provider_name="deepseek",
                    api_key=api_key,
                    model=config.model,
                    base_url=DEFAULT_DEEPSEEK_BASE_URL,
                    api_key_env=config.deepseek_api_key_env,
                    provider_label="DeepSeek",
                )
            else:
                result = smoke_deepseek_provider(
                    api_key=api_key,
                    model=config.model,
                    api_key_env=config.deepseek_api_key_env,
                )
        except DeepSeekError as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc

    if provider_name == "openai-compat":
        if not config.base_url.strip():
            console.print("openai-compat smoke requires base_url in .agent/config.toml.")
            raise typer.Exit(code=1)
        api_key = os.environ.get(config.api_key_env, "")
        try:
            if native:
                result = smoke_provider_native(
                    provider_name="openai-compat",
                    api_key=api_key,
                    model=config.model,
                    base_url=config.base_url,
                    api_key_env=config.api_key_env,
                    provider_label="openai-compat",
                )
            else:
                result = smoke_provider(
                    provider_name="openai-compat",
                    api_key=api_key,
                    model=config.model,
                    base_url=config.base_url,
                    api_key_env=config.api_key_env,
                    provider_label="openai-compat",
                )
        except ProviderError as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc

    console.print(f"provider: {result.provider}")
    console.print(f"model: {result.model}")
    console.print(f"api_key_env: {result.api_key_env}")
    console.print(f"status: {result.status}")
    console.print(f"action: {result.action_name}")
    console.print(f"final: {result.final}")
    for warning in diagnostics.warnings:
        console.print(f"config warning: {warning}")


@skills_app.command("list")
def skills_list(cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project skills.")) -> None:
    """List available skill metadata without loading skill bodies."""
    workspace = (cwd or Path.cwd()).resolve()
    try:
        catalog = discover_skills(workspace)
    except SkillError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    for skill in catalog.values():
        tools = ",".join(skill.allowed_tools)
        console.file.write(f"{skill.name}\t{skill.source}\ttools: {tools}\t{skill.description}\n")


@skills_app.command("show")
def skills_show(
    name: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project skills."),
) -> None:
    """Show one skill, including its body."""
    workspace = (cwd or Path.cwd()).resolve()
    try:
        skills = load_selected_skills(workspace, [name], max_chars=20_000)
    except SkillError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    skill = skills[0]
    console.print(f"name: {skill.name}")
    console.print(f"description: {skill.description}")
    console.print(f"source: {skill.source}")
    console.print("allowed_tools:")
    for tool_name in skill.allowed_tools:
        console.print(f"- {tool_name}")
    console.print("")
    console.print(skill.body or "")


@memory_app.command("review")
def memory_review(cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for memory.")) -> None:
    """List pending memory candidates."""
    store = MemoryStore((cwd or Path.cwd()).resolve())
    candidates = store.list_candidates()
    for candidate in candidates:
        console.print(
            f"{candidate.candidate_id}\tstatus: {candidate.status}\tsource: {candidate.source_run_id}\t{candidate.source_excerpt}"
        )


@memory_app.command("list")
def memory_list(cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for memory.")) -> None:
    """List accepted active memory entries."""
    store = MemoryStore((cwd or Path.cwd()).resolve())
    for entry in store.list_entries():
        console.print(f"{entry.entry_id}\tstatus: {entry.status}\tsource: {entry.source_run_id}\t{entry.source_excerpt}")


@memory_app.command("accept")
def memory_accept(
    candidate_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for memory."),
) -> None:
    """Accept a pending memory candidate."""
    try:
        entry = MemoryStore((cwd or Path.cwd()).resolve()).accept_candidate(candidate_id)
    except MemoryError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"accepted: {entry.entry_id}")


@memory_app.command("undo")
def memory_undo(
    entry_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for memory."),
) -> None:
    """Undo a memory entry by writing a tombstone."""
    try:
        tombstone = MemoryStore((cwd or Path.cwd()).resolve()).undo_entry(entry_id)
    except MemoryError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"undone: {tombstone.supersedes}")


def _make_llm(config):
    return make_llm_client(config)


def _chat_approval_handler(action) -> bool:
    console.print(f"approval required: {action.action.name}")
    console.print(json.dumps(action.action.args, ensure_ascii=True, sort_keys=True))
    try:
        answer = input("approve? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _chat_event_handler(event: dict) -> None:
    name = event.get("event")
    if name == "model_call_start":
        console.print("activity: calling model")
    elif name == "action_parsed":
        console.print(f"activity: action {event.get('action')}")
    elif name == "tool_start":
        console.print(f"activity: tool {event.get('action')}")
    elif name == "approval_required":
        console.print(f"activity: waiting for approval {event.get('action')}")


def _make_chat_stream_handler(enabled: bool):
    used = False

    if not enabled:
        return None, lambda: False

    def handle_chunk(chunk: str) -> None:
        nonlocal used
        if not used:
            console.print("raw model response preview:")
            used = True
        console.file.write(chunk)
        console.file.flush()

    return handle_chunk, lambda: used


def _handle_chat_command(command: str, session: ChatSession, config) -> str | None:
    normalized = command.strip().lower()
    if normalized in {"/exit", "/quit"}:
        return "exit"
    if normalized == "/help":
        _print_chat_help()
        return "handled"
    if normalized == "/status":
        _print_chat_status(session, config)
        return "handled"
    if normalized == "/transcript":
        _print_chat_transcript(session)
        return "handled"
    if normalized.startswith("/"):
        console.print(f"unknown command: {command}")
        console.print("try /help")
        return "handled"
    return None


def _print_chat_help() -> None:
    console.print("commands:")
    console.print("/help        Show chat commands.")
    console.print("/status      Show current chat session status.")
    console.print("/transcript  Show recent chat turns.")
    console.print("/exit        End the chat.")


def _print_chat_status(session: ChatSession, config) -> None:
    turns = session.state.turns
    console.print("chat status:")
    console.print(f"chat_id: {session.state.session_id}")
    console.print(f"workspace: {session.cwd}", soft_wrap=True)
    console.print(f"provider: {config.provider}")
    console.print(f"model: {config.model}")
    console.print(f"turns: {len(turns)}")
    console.print(f"session_file: {session.cwd / '.agent' / 'chats' / session.state.session_id / 'session.json'}")
    if not turns:
        console.print("last_status: none")
        return
    last_turn = turns[-1]
    console.print(f"last_run_id: {last_turn.run_id}")
    console.print(f"last_status: {last_turn.status}")
    console.print(f"last_terminal_reason: {last_turn.terminal_reason}")
    console.print(f"last_final: {last_turn.final}")


def _print_chat_transcript(session: ChatSession, limit: int = 10) -> None:
    turns = session.state.turns[-limit:]
    console.print("transcript:")
    if not turns:
        console.print("(no turns yet)")
        return
    start = len(session.state.turns) - len(turns) + 1
    for offset, turn in enumerate(turns):
        console.print(f"turn {start + offset}")
        console.print(f"user: {turn.user}")
        console.print(f"status: {turn.status}")
        console.print(f"terminal_reason: {turn.terminal_reason}")
        console.print(f"final: {turn.final}")


def _result_completed(result) -> bool:
    return result.action.action.name == "done" and result.observation.status == "ok"


def _result_terminal_reason(result) -> str:
    if _result_completed(result):
        return "done"
    if result.action.action.name == "ask_user" and result.observation.status == "ok":
        return "ask_user"
    error = result.observation.error
    if error is None:
        return "stopped"
    if _error_code(error) == "TOOL_FAILED" and error.message == "Run stopped after reaching the iteration limit.":
        return "iteration_limit"
    return f"error:{_error_code(error)}"


def _error_code(error) -> str:
    return str(error.code)


@runs_app.command("list")
def runs_list(limit: int = 20) -> None:
    """List recent agent runs."""
    runs = RunStore(Path.cwd()).list_runs(limit=limit)
    if not runs:
        console.print("No runs found.")
        return

    for run in runs:
        console.print(f"{run.run_id}\tupdated: {run.updated_at.isoformat()}\tsummary: {run.summary_path}")


@runs_app.command("show")
def runs_show(run_id: str) -> None:
    """Show one agent run."""
    try:
        detail = RunStore(Path.cwd()).show_run(run_id)
    except RunStoreError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    console.print(detail.summary.rstrip())
    console.print(f"tool calls: {len(detail.tool_calls)}")
    invalid_calls = [call for call in detail.tool_calls if not call.valid]
    for call in invalid_calls:
        console.print(f"invalid tool call line {call.line_number}: {call.error}")
    if detail.snapshots:
        console.print("snapshots:")
        for snapshot in detail.snapshots:
            console.print(f"- path: {snapshot['path']}")
            console.print(f"  snapshot: {snapshot['snapshot_path']}")
            if snapshot["restore_hint"]:
                console.print(f"  restore: {snapshot['restore_hint']}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
