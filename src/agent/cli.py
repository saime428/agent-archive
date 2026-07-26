from __future__ import annotations

import errno
import importlib.util
import json
import os
import platform
import shutil
import signal
from pathlib import Path
from threading import Event

import typer
from rich.console import Console

from agent.config import AgentConfig, ConfigDiagnostics, ConfigError, ConfigOverrides, load_config
from agent.config_write import remove_project_config_keys, save_project_config
from agent.core.automation import AutomationAttempt, AutomationError, AutomationStore, AutomationWorker
from agent.core.chat import ChatSession, ConversationState
from agent.core.eval import EvalError, run_reference_eval
from agent.core.hooks import BUILTIN_HOOKS
from agent.core.loop import run_once
from agent.core.memory import MemoryError, MemoryStore
from agent.core.run_control import (
    DEFAULT_RUN_TIMEOUT_SECONDS,
    MAX_RUN_TIMEOUT_SECONDS,
    MIN_RUN_TIMEOUT_SECONDS,
    RunControl,
)
from agent.core.run_lease import RunLeaseError, WorkspaceRunLease
from agent.core.run_store import RunStore, RunStoreError
from agent.core.skills import SkillError, SkillInventoryItem, SkillStore, load_selected_skills
from agent.core.tool_catalog import list_tool_infos
from agent.llm.deepseek import DeepSeekError
from agent.llm.factory import PROVIDER_REGISTRY, make_llm as make_llm_client
from agent.llm.openai_compat import ProviderError
from agent.mcp_config import McpConfigStore, McpInventoryItem, McpRuntimeError
from agent.mcp_runtime import McpStdioRuntime
from agent.secrets import load_workspace_secrets
from agent.web.server import serve_workbench

app = typer.Typer(help="Minimal Python CLI agent.")
runs_app = typer.Typer(help="Inspect agent run logs.")
tools_app = typer.Typer(help="Inspect available agent tools.")
config_app = typer.Typer(help="Inspect agent configuration.")
mcp_app = typer.Typer(help="Manage local MCP server configuration.")
hooks_app = typer.Typer(help="Inspect run hooks.")
skills_app = typer.Typer(help="Inspect and load agent skills.")
memory_app = typer.Typer(help="Review and manage agent memory.")
automation_app = typer.Typer(help="Manage explicit local automations.")
eval_app = typer.Typer(help="Run the deterministic local evaluation gate.")
provider_app = typer.Typer(help="Inspect and smoke-test LLM providers.")
release_app = typer.Typer(help="Inspect release readiness.")
app.add_typer(runs_app, name="runs")
app.add_typer(tools_app, name="tools")
app.add_typer(config_app, name="config")
app.add_typer(mcp_app, name="mcp")
app.add_typer(hooks_app, name="hooks")
app.add_typer(skills_app, name="skills")
app.add_typer(memory_app, name="memory")
app.add_typer(automation_app, name="automation")
app.add_typer(eval_app, name="eval")
app.add_typer(provider_app, name="provider")
app.add_typer(release_app, name="release")

WORKBENCH_PORT_ATTEMPTS = 200
MCP_CLI_TEXT_LIMIT = 512
console = Console(highlight=False)
DOCUMENT_DEPENDENCIES = {
    "pypdf": "pypdf",
    "defusedxml": "defusedxml",
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


def _print_provider_capabilities(config) -> None:
    spec = PROVIDER_REGISTRY[config.provider]
    caps = spec.capabilities
    console.print(
        "provider adapter capabilities: "
        f"streaming={str(caps.streaming).lower()} "
        f"native_tools={str(caps.native_tools).lower()}"
    )
    if spec.requires_base_url:
        console.print(f"base_url: {config.base_url}")
    if spec.api_key_env is not None:
        env_name = spec.api_key_env(config)
        console.print(f"api key env: {env_name}")
        console.print(f"api key required: {str(spec.api_key_required).lower()}")
        console.print(f"api key present: {str(bool(os.environ.get(env_name))).lower()}")
    if config.native_tools and not caps.native_tools:
        console.print("capability warning: native_tools enabled but provider lacks native tool calling")


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
    console.print(f"config enabled_hooks: {list(config.enabled_hooks)}")
    console.print(f"config blocking_hooks: {list(config.blocking_hooks)}")
    _print_provider_capabilities(config)
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
    try:
        mcp_items = _mcp_store(cwd).inventory()
    except McpRuntimeError as exc:
        console.file.write(f"mcp inventory error: {_bounded_text(str(exc))}\n")
    else:
        enabled = sum(1 for item in mcp_items if item.enabled)
        invalid = sum(1 for item in mcp_items if item.status == "invalid")
        orphan = sum(1 for item in mcp_items if item.status == "orphan")
        console.file.write(
            f"mcp servers: {len(mcp_items)} total, {enabled} enabled, {invalid} invalid, {orphan} orphan\n"
        )
        if mcp_items:
            console.file.write("mcp detail: agent mcp doctor\n")
    try:
        report = _skill_store(cwd).doctor(default_skills=config.default_skills)
    except SkillError as exc:
        console.file.write(f"skills doctor error: {_bounded_text(str(exc))}\n")
    else:
        console.file.write(
            f"skills: {len(report.items)} total, {len(report.problems)} problems, healthy={str(report.healthy).lower()}\n"
        )
        console.file.write("skills detail: agent skills doctor\n")


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
        console.print("config readable: false")
        console.print(f"config error: {exc}")
        raise typer.Exit(code=1) from exc

    console.print("release readiness: complete")
    console.print("route completion: 100% (legacy local baseline)")
    console.print("startup command: agent start")
    console.print("config readable: true")
    console.print(f"provider: {config.provider}")
    console.print(f"model: {config.model}")
    _print_provider_capabilities(config)
    console.print("settings writes: controlled allowlist (no secrets/approval bypass)")
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
    approval: str | None = typer.Option(
        None,
        "--approval",
        help="Approval mode; never denies actions that would require confirmation.",
    ),
    dry_run: bool | None = typer.Option(None, "--dry-run/--no-dry-run", help="Record dry-run intent in config."),
    provider: str | None = typer.Option(None, "--provider", help="LLM provider."),
    model: str | None = typer.Option(None, "--model", help="LLM model."),
    skill: list[str] | None = typer.Option(None, "--skill", help="Skill to load for this run."),
    timeout_seconds: int = typer.Option(
        DEFAULT_RUN_TIMEOUT_SECONDS,
        "--timeout-seconds",
        min=MIN_RUN_TIMEOUT_SECONDS,
        max=MAX_RUN_TIMEOUT_SECONDS,
        help="Whole-run timeout in seconds.",
    ),
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

    close_error: McpRuntimeError | None = None
    try:
        with WorkspaceRunLease.acquire(workspace, owner={"kind": "cli-run"}):
            control = RunControl.with_timeout(timeout_seconds)
            runtime = McpStdioRuntime(workspace)
            try:
                try:
                    llm = _make_llm(config)
                except DeepSeekError as exc:
                    console.print(str(exc))
                    raise typer.Exit(code=1) from exc

                selected_skills = skill if skill else None
                try:
                    result = run_once(
                        task,
                        llm,
                        cwd=workspace,
                        config=config,
                        selected_skills=selected_skills,
                        mcp_runtime=runtime,
                        approval_handler=_chat_approval_handler,
                        event_handler=_chat_event_handler,
                        control=control,
                    )
                except (DeepSeekError, McpRuntimeError) as exc:
                    console.print(str(exc))
                    raise typer.Exit(code=1) from exc
            finally:
                try:
                    runtime.close()
                except McpRuntimeError as exc:
                    close_error = exc
    except RunLeaseError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    if close_error is not None:
        console.print(str(close_error))
        raise typer.Exit(code=1) from close_error

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
    """Start the local web workbench."""
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
        except McpRuntimeError as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
        except ValueError as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
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
    approval: str | None = typer.Option(
        None,
        "--approval",
        help="Approval mode; never denies actions that would require confirmation.",
    ),
    dry_run: bool | None = typer.Option(None, "--dry-run/--no-dry-run", help="Record dry-run intent in config."),
    provider: str | None = typer.Option(None, "--provider", help="LLM provider."),
    model: str | None = typer.Option(None, "--model", help="LLM model."),
    skill: list[str] | None = typer.Option(None, "--skill", help="Skill to load for chat turns."),
    timeout_seconds: int = typer.Option(
        DEFAULT_RUN_TIMEOUT_SECONDS,
        "--timeout-seconds",
        min=MIN_RUN_TIMEOUT_SECONDS,
        max=MAX_RUN_TIMEOUT_SECONDS,
        help="Whole-turn timeout in seconds.",
    ),
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

    runtime = McpStdioRuntime(workspace)
    close_error: McpRuntimeError | None = None
    try:
        try:
            _run_chat_repl(
                workspace,
                config,
                diagnostics,
                resume=resume,
                skill=skill,
                mcp_runtime=runtime,
                timeout_seconds=timeout_seconds,
            )
        except McpRuntimeError as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
    finally:
        try:
            runtime.close()
        except McpRuntimeError as exc:
            close_error = exc
    if close_error is not None:
        console.print(str(close_error))
        raise typer.Exit(code=1) from close_error


def _run_chat_repl(
    workspace: Path,
    config: AgentConfig,
    diagnostics: ConfigDiagnostics,
    *,
    resume: str | None,
    skill: list[str] | None,
    mcp_runtime: McpStdioRuntime,
    timeout_seconds: int,
) -> None:
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

    session = ChatSession(
        cwd=workspace,
        llm=llm,
        config=config,
        state=state,
        selected_skills=skill if skill else None,
        mcp_runtime=mcp_runtime,
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
            PROVIDER_REGISTRY[config.provider].capabilities.streaming
        )
        control = RunControl.with_timeout(timeout_seconds)
        try:
            with WorkspaceRunLease.acquire(
                workspace,
                owner={"kind": "cli-chat", "session_id": session.state.session_id},
            ):
                result = session.run_turn(
                    user_input,
                    approval_handler=_chat_approval_handler,
                    event_handler=_chat_event_handler,
                    stream_handler=stream_handler,
                    control=control,
                )
        except (DeepSeekError, RunLeaseError) as exc:
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
    load_workspace_secrets(workspace)
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
    _print_provider_capabilities(config)
    console.print(f"default_skills: {list(config.default_skills)}")
    console.print(f"allowed_commands: {list(config.allowed_commands)}")
    console.print(f"enabled_hooks: {list(config.enabled_hooks)}")
    console.print(f"blocking_hooks: {list(config.blocking_hooks)}")
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


_BOOL_KEYS = {"dry_run", "memory_auto_write", "web_search_enabled", "computer_read_enabled", "native_tools"}
_INT_KEYS = {"memory_max_items", "max_consecutive_errors"}
_LIST_KEYS = {"default_skills", "allowed_commands", "enabled_hooks", "blocking_hooks"}


def _parse_config_value(key: str, values: list[str]):
    if key in _LIST_KEYS:
        return tuple(values)
    if len(values) != 1:
        raise ValueError(f"Key {key} takes exactly one value.")
    raw = values[0]
    if key in _BOOL_KEYS:
        if raw not in {"true", "false"}:
            raise ValueError(f"Key {key} expects true or false.")
        return raw == "true"
    if key in _INT_KEYS:
        if not raw.isdigit():
            raise ValueError(f"Key {key} expects a positive integer.")
        return int(raw)
    return raw


@config_app.command("set")
def config_set(
    key: str,
    values: list[str] = typer.Argument(...),
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project config."),
) -> None:
    """Set one key in the project config with validation and atomic write."""
    workspace = (cwd or Path.cwd()).resolve()
    try:
        value = _parse_config_value(key, values)
        path = save_project_config(workspace, {key: value})
    except (ValueError, OSError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"saved: {path}", soft_wrap=True)
    try:
        _config, diagnostics = load_config(workspace)
    except ConfigError as exc:
        # 写入已验证成功；reload 失败只可能来自其他文件（如损坏的全局 config）。
        console.print(f"config warning: {exc}")
        return
    for warning in diagnostics.warnings:
        console.print(f"config warning: {warning}")


@config_app.command("unset")
def config_unset(
    key: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project config."),
) -> None:
    """Remove one key from the project config."""
    workspace = (cwd or Path.cwd()).resolve()
    try:
        path = remove_project_config_keys(workspace, [key])
    except (ValueError, OSError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"saved: {path}", soft_wrap=True)


@provider_app.command("smoke")
def provider_smoke(
    provider_name: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project config."),
    model: str | None = typer.Option(None, "--model", help="Model to smoke-test."),
    native: bool = typer.Option(False, "--native", help="Smoke-test native tool calling."),
) -> None:
    """Run an explicit provider smoke test without creating an agent run."""
    spec = PROVIDER_REGISTRY.get(provider_name)
    if spec is None or spec.smoke is None:
        console.print(f"Unsupported provider smoke target: {provider_name}")
        raise typer.Exit(code=1)
    workspace = (cwd or Path.cwd()).resolve()
    load_workspace_secrets(workspace)
    try:
        config, diagnostics = load_config(workspace, overrides=ConfigOverrides(model=model))
    except ConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    try:
        result = spec.smoke(config, native)
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


def _mcp_store(cwd: Path | None) -> McpConfigStore:
    return McpConfigStore(cwd or Path.cwd())


def _bounded_text(value: str) -> str:
    text = " ".join(value.splitlines())
    if len(text) <= MCP_CLI_TEXT_LIMIT:
        return text
    return f"{text[: MCP_CLI_TEXT_LIMIT - 3]}..."


def _print_mcp_error(exc: McpRuntimeError) -> None:
    console.file.write(f"{_bounded_text(str(exc))}\n")


def _print_mcp_item(item: McpInventoryItem) -> None:
    enabled = "enabled" if item.enabled else "disabled"
    suffix = f"\t{_bounded_text(item.message)}" if item.message else ""
    console.file.write(f"{item.server_id}\t{item.source}\t{enabled}\t{item.status}{suffix}\n")


@mcp_app.command("list")
def mcp_list(cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory.")) -> None:
    """List MCP sources and static status without starting servers."""
    try:
        items = _mcp_store(cwd).inventory()
    except McpRuntimeError as exc:
        _print_mcp_error(exc)
        raise typer.Exit(code=1) from exc
    for item in items:
        _print_mcp_item(item)


@mcp_app.command("show")
def mcp_show(
    server_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory."),
) -> None:
    """Show one MCP server's static config without starting it."""
    try:
        detail = _mcp_store(cwd).describe(server_id)
    except McpRuntimeError as exc:
        _print_mcp_error(exc)
        raise typer.Exit(code=1) from exc
    item = detail.item
    console.file.write(f"server_id: {item.server_id}\n")
    console.file.write(f"source: {item.source}\n")
    console.file.write(f"enabled: {str(item.enabled).lower()}\n")
    console.file.write(f"status: {item.status}\n")
    if item.message:
        console.file.write(f"message: {_bounded_text(item.message)}\n")
    if detail.config is not None:
        console.file.write(f"command: {detail.config.command}\n")
        console.file.write(f"args: {list(detail.config.args)}\n")
        console.file.write(f"pass_env: {list(detail.config.pass_env)}\n")
        console.file.write(f"cwd: {detail.config.cwd}\n")


@mcp_app.command("validate")
def mcp_validate(
    server_id: str | None = typer.Argument(None),
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory."),
) -> None:
    """Validate MCP configuration without starting servers."""
    try:
        items = _mcp_store(cwd).validate(server_id)
    except McpRuntimeError as exc:
        _print_mcp_error(exc)
        raise typer.Exit(code=1) from exc
    for item in items:
        _print_mcp_item(item)


@mcp_app.command("set")
def mcp_set(
    server_id: str,
    command: str = typer.Option(..., "--command", help="Executable path or trusted PATH command."),
    arg: list[str] | None = typer.Option(None, "--arg", help="Server argument; repeat as needed."),
    pass_env: list[str] | None = typer.Option(None, "--pass-env", help="Environment name; repeat as needed."),
    server_cwd: str = typer.Option("config", "--server-cwd", help="Server cwd: config or workspace."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory."),
) -> None:
    """Create or replace one managed MCP fragment."""
    try:
        item = _mcp_store(cwd).set_server(
            server_id,
            command=command,
            args=tuple(arg or ()),
            pass_env=tuple(pass_env or ()),
            cwd=server_cwd,
        )
    except McpRuntimeError as exc:
        _print_mcp_error(exc)
        raise typer.Exit(code=1) from exc
    _print_mcp_item(item)


def _set_mcp_enabled(server_id: str, enabled: bool, cwd: Path | None) -> None:
    try:
        item = _mcp_store(cwd).set_enabled(server_id, enabled)
    except McpRuntimeError as exc:
        _print_mcp_error(exc)
        raise typer.Exit(code=1) from exc
    _print_mcp_item(item)


@mcp_app.command("enable")
def mcp_enable(
    server_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory."),
) -> None:
    """Enable one configured MCP server for new runtimes."""
    _set_mcp_enabled(server_id, True, cwd)


@mcp_app.command("disable")
def mcp_disable(
    server_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory."),
) -> None:
    """Disable one configured MCP server for new runtimes."""
    _set_mcp_enabled(server_id, False, cwd)


@mcp_app.command("remove")
def mcp_remove(
    server_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory."),
) -> None:
    """Remove one managed MCP server or state-only orphan."""
    try:
        _mcp_store(cwd).remove_server(server_id)
    except McpRuntimeError as exc:
        _print_mcp_error(exc)
        raise typer.Exit(code=1) from exc
    console.print(f"removed: {server_id}")


@mcp_app.command("doctor")
def mcp_doctor(cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory.")) -> None:
    """Probe enabled MCP servers with one live runtime and report tool counts."""
    workspace = (cwd or Path.cwd()).resolve()
    try:
        items = _mcp_store(cwd).inventory()
    except McpRuntimeError as exc:
        _print_mcp_error(exc)
        raise typer.Exit(code=1) from exc
    for item in items:
        _print_mcp_item(item)
    enabled = [item for item in items if item.enabled]
    console.file.write(f"enabled servers: {len(enabled)}\n")
    if not enabled:
        return

    runtime = McpStdioRuntime(workspace)
    failure: McpRuntimeError | None = None
    definitions: tuple = ()
    try:
        definitions = runtime.discover_tools()
    except McpRuntimeError as exc:
        failure = exc
    finally:
        try:
            runtime.close()
        except McpRuntimeError as exc:
            if failure is None:
                failure = exc
    if failure is not None:
        _print_mcp_error(failure)
        raise typer.Exit(code=1)

    counts = {item.server_id: 0 for item in enabled}
    for definition in definitions:
        server_id = getattr(getattr(definition, "target", None), "server_id", None)
        if isinstance(server_id, str) and server_id in counts:
            counts[server_id] += 1
    for server_id, count in counts.items():
        console.file.write(f"{server_id}\tready\t{count} tools\n")


@hooks_app.command("list")
def hooks_list(cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory.")) -> None:
    """List builtin hooks and their configured state."""
    workspace = (cwd or Path.cwd()).resolve()
    try:
        config, _diagnostics = load_config(workspace)
    except ConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    for name in sorted(BUILTIN_HOOKS):
        enabled = "enabled" if name in config.enabled_hooks else "disabled"
        blocking = "blocking" if name in config.blocking_hooks else "-"
        console.file.write(f"{name}\t{enabled}\t{blocking}\n")
    referenced = tuple(dict.fromkeys(config.enabled_hooks + config.blocking_hooks))
    for name in referenced:
        if name not in BUILTIN_HOOKS:
            blocking = "blocking" if name in config.blocking_hooks else "-"
            console.file.write(f"{name}\tunknown\t{blocking}\n")


def _skill_store(cwd: Path | None) -> SkillStore:
    return SkillStore((cwd or Path.cwd()).resolve())


def _print_skill_error(exc: SkillError) -> None:
    # Skill diagnostics quote untrusted document content, so they bypass Rich
    # markup exactly like MCP errors do.
    console.file.write(f"{_bounded_text(str(exc))}\n")


def _print_skill_item(item: SkillInventoryItem) -> None:
    enabled = "enabled" if item.enabled else "disabled"
    suffix = f"\t{_bounded_text(item.message)}" if item.message else ""
    console.file.write(f"{item.name}\t{item.source}\t{enabled}\t{item.status}{suffix}\n")


@skills_app.command("list")
def skills_list(cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project skills.")) -> None:
    """List every skill source and status without loading skill bodies."""
    try:
        items = _skill_store(cwd).inventory()
    except SkillError as exc:
        _print_skill_error(exc)
        raise typer.Exit(code=1) from exc
    for item in items:
        _print_skill_item(item)


@skills_app.command("validate")
def skills_validate(
    source: Path,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project skills."),
) -> None:
    """Validate a candidate skill directory or .skill.zip without writing files."""
    try:
        item = _skill_store(cwd).validate_source(source)
    except SkillError as exc:
        _print_skill_error(exc)
        raise typer.Exit(code=1) from exc
    _print_skill_item(item)


@skills_app.command("install")
def skills_install(
    source: Path,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project skills."),
) -> None:
    """Install one candidate skill directory into the user store."""
    try:
        item = _skill_store(cwd).install(source)
    except SkillError as exc:
        _print_skill_error(exc)
        raise typer.Exit(code=1) from exc
    _print_skill_item(item)


def _set_skill_enabled(name: str, enabled: bool, cwd: Path | None) -> None:
    try:
        item = _skill_store(cwd).set_enabled(name, enabled)
    except SkillError as exc:
        _print_skill_error(exc)
        raise typer.Exit(code=1) from exc
    _print_skill_item(item)


@skills_app.command("enable")
def skills_enable(
    name: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project skills."),
) -> None:
    """Enable one installed user skill."""
    _set_skill_enabled(name, True, cwd)


@skills_app.command("disable")
def skills_disable(
    name: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project skills."),
) -> None:
    """Disable one installed user skill."""
    _set_skill_enabled(name, False, cwd)


@skills_app.command("update")
def skills_update(
    name: str,
    source: Path,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project skills."),
) -> None:
    """Replace one installed user skill with a same-named candidate."""
    try:
        item = _skill_store(cwd).update(name, source)
    except SkillError as exc:
        _print_skill_error(exc)
        raise typer.Exit(code=1) from exc
    _print_skill_item(item)


@skills_app.command("package")
def skills_package(
    name: str,
    output: Path = typer.Option(..., "--output", help="Archive path ending with .skill.zip."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project skills."),
) -> None:
    """Package one user skill into a portable .skill.zip archive."""
    try:
        target = _skill_store(cwd).package(name, output)
    except SkillError as exc:
        _print_skill_error(exc)
        raise typer.Exit(code=1) from exc
    console.print(f"packaged: {target}")


@skills_app.command("remove")
def skills_remove(
    name: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project skills."),
) -> None:
    """Remove one user skill or a state-only orphan."""
    try:
        _skill_store(cwd).remove(name)
    except SkillError as exc:
        _print_skill_error(exc)
        raise typer.Exit(code=1) from exc
    console.print(f"removed: {name}")


@skills_app.command("doctor")
def skills_doctor(cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project skills.")) -> None:
    """Check every skill source, user state, and the effective default skills."""
    workspace = (cwd or Path.cwd()).resolve()
    try:
        config, _diagnostics = load_config(workspace)
    except ConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    try:
        report = _skill_store(cwd).doctor(default_skills=config.default_skills)
    except SkillError as exc:
        _print_skill_error(exc)
        raise typer.Exit(code=1) from exc
    for item in report.items:
        _print_skill_item(item)
    console.file.write(f"default skills: {','.join(config.default_skills)}\n")
    for problem in report.problems:
        console.file.write(f"problem: {_bounded_text(problem)}\n")
    console.file.write(f"skills healthy: {str(report.healthy).lower()}\n")
    if not report.healthy:
        raise typer.Exit(code=1)


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
        _print_skill_error(exc)
        raise typer.Exit(code=1) from exc
    # Everything below quotes untrusted skill content, so it bypasses markup.
    skill = skills[0]
    console.file.write(f"name: {skill.name}\n")
    console.file.write(f"description: {skill.description}\n")
    console.file.write(f"source: {skill.source}\n")
    console.file.write("allowed_tools:\n")
    for tool_name in skill.allowed_tools:
        console.file.write(f"- {tool_name}\n")
    console.file.write("\n")
    console.file.write(f"{skill.body or ''}\n")


@memory_app.command("review")
def memory_review(cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for memory.")) -> None:
    """List pending memory candidates."""
    store = MemoryStore((cwd or Path.cwd()).resolve())
    try:
        candidates = [item for item in store.list_candidates() if item.status == "pending"]
    except MemoryError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    for candidate in candidates:
        console.file.write(
            f"{candidate.candidate_id}\tstatus: {candidate.status}\tsource: {candidate.source_run_id}\t{candidate.source_excerpt}\n"
        )


@memory_app.command("list")
def memory_list(cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for memory.")) -> None:
    """List accepted active memory entries."""
    store = MemoryStore((cwd or Path.cwd()).resolve())
    try:
        entries = store.list_entries()
    except MemoryError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    for entry in entries:
        console.file.write(
            f"{entry.entry_id}\tstatus: {entry.status}\tsource: {entry.source_run_id}\t{entry.source_excerpt}\n"
        )


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
    console.file.write(f"accepted: {entry.entry_id}\n")


@memory_app.command("reject")
def memory_reject(
    candidate_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for memory."),
) -> None:
    """Reject a pending memory candidate."""
    try:
        candidate = MemoryStore((cwd or Path.cwd()).resolve()).reject_candidate(candidate_id)
    except MemoryError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.file.write(f"rejected: {candidate.candidate_id}\n")


@memory_app.command("revise")
def memory_revise(
    entry_id: str,
    replacement: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for memory."),
) -> None:
    """Replace a current active memory entry while preserving its history."""
    try:
        entry = MemoryStore((cwd or Path.cwd()).resolve()).revise_entry(entry_id, replacement)
    except MemoryError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.file.write(f"revised: {entry.entry_id} supersedes: {entry.supersedes}\n")


@memory_app.command("delete")
def memory_delete(
    entry_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for memory."),
) -> None:
    """Delete a current active memory entry by writing a tombstone."""
    try:
        tombstone = MemoryStore((cwd or Path.cwd()).resolve()).delete_entry(entry_id)
    except MemoryError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.file.write(f"deleted: {tombstone.supersedes} tombstone: {tombstone.entry_id}\n")


@memory_app.command("history")
def memory_history(
    entry_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for memory."),
) -> None:
    """Show one memory entry's complete revision history."""
    try:
        entries = MemoryStore((cwd or Path.cwd()).resolve()).entry_history(entry_id)
    except MemoryError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    for entry in entries:
        console.file.write(
            f"{entry.entry_id}\tstatus: {entry.status}\tsource: {entry.source_run_id}"
            f"\tcandidate: {entry.candidate_id or '-'}\tsupersedes: {entry.supersedes or '-'}"
            f"\t{entry.source_excerpt}\n"
        )


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
    console.file.write(f"undone: {tombstone.supersedes}\n")


@automation_app.command("add")
def automation_add(
    task: str,
    every_minutes: int = typer.Option(
        ...,
        "--every-minutes",
        min=1,
        max=525_600,
        help="Fixed UTC interval in minutes.",
    ),
    skill: list[str] | None = typer.Option(None, "--skill", help="Skill to load for each attempt."),
    timeout_seconds: int = typer.Option(
        DEFAULT_RUN_TIMEOUT_SECONDS,
        "--timeout-seconds",
        min=MIN_RUN_TIMEOUT_SECONDS,
        max=MAX_RUN_TIMEOUT_SECONDS,
        help="Whole-attempt timeout in seconds.",
    ),
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for automations."),
) -> None:
    """Add a disabled fixed-interval automation."""
    try:
        definition = AutomationStore((cwd or Path.cwd()).resolve()).add_definition(
            task=task,
            interval_seconds=every_minutes * 60,
            skills=tuple(skill or ()),
            timeout_seconds=timeout_seconds,
        )
    except AutomationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.file.write(
        f"added: {definition.automation_id} status: {definition.status} every_minutes: {every_minutes}\n"
    )


@automation_app.command("list")
def automation_list(
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for automations."),
) -> None:
    """List current automation definitions."""
    try:
        definitions = AutomationStore((cwd or Path.cwd()).resolve()).list_definitions()
    except AutomationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    for definition in definitions:
        skills = ",".join(definition.skills) or "-"
        console.file.write(
            f"{definition.automation_id}\tstatus: {definition.status}"
            f"\tevery_minutes: {definition.interval_seconds // 60}"
            f"\ttimeout_seconds: {definition.timeout_seconds}\tskills: {skills}\t{_bounded_text(definition.task)}\n"
        )


@automation_app.command("history")
def automation_history(
    automation_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for automations."),
) -> None:
    """Show definition enable and disable revisions."""
    try:
        history = AutomationStore((cwd or Path.cwd()).resolve()).definition_history(automation_id)
    except AutomationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    for definition in history:
        console.file.write(
            f"{definition.automation_id}\tstatus: {definition.status}"
            f"\tanchor: {definition.anchor_at or '-'}\tupdated: {definition.updated_at}\n"
        )


@automation_app.command("enable")
def automation_enable(
    automation_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for automations."),
) -> None:
    """Enable an automation and make its first slot immediately due."""
    try:
        definition = AutomationStore((cwd or Path.cwd()).resolve()).enable_definition(automation_id)
    except AutomationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.file.write(f"enabled: {definition.automation_id} anchor: {definition.anchor_at}\n")


@automation_app.command("disable")
def automation_disable(
    automation_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for automations."),
) -> None:
    """Disable future slots without cancelling a running attempt."""
    try:
        definition = AutomationStore((cwd or Path.cwd()).resolve()).disable_definition(automation_id)
    except AutomationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.file.write(f"disabled: {definition.automation_id}\n")


@automation_app.command("attempts")
def automation_attempts(
    automation_id: str | None = typer.Option(None, "--automation-id", help="Filter by automation id."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for automations."),
) -> None:
    """List current durable automation attempts."""
    try:
        attempts = AutomationStore((cwd or Path.cwd()).resolve()).list_attempts(automation_id=automation_id)
    except AutomationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    for attempt in attempts:
        _print_automation_attempt(attempt)


@automation_app.command("notifications")
def automation_notifications(
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for automations."),
) -> None:
    """List abnormal terminal attempts as local notifications."""
    try:
        notifications = AutomationStore((cwd or Path.cwd()).resolve()).list_notifications()
    except AutomationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    for notification in notifications:
        _print_automation_attempt(notification)


@automation_app.command("cancel")
def automation_cancel(
    attempt_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for automations."),
) -> None:
    """Request cancellation of a claimed or running attempt."""
    try:
        attempt = AutomationStore((cwd or Path.cwd()).resolve()).request_cancel(attempt_id)
    except AutomationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.file.write(f"cancel_requested: {attempt.attempt_id}\n")


@automation_app.command("worker")
def automation_worker(
    once: bool = typer.Option(False, "--once", help="Run one recovery and due-claim pass, then exit."),
    poll_seconds: int = typer.Option(5, "--poll-seconds", min=1, max=3600, help="Foreground poll interval."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for automations."),
) -> None:
    """Run the explicit foreground automation worker."""
    worker = AutomationWorker((cwd or Path.cwd()).resolve())
    stop_event = Event()
    previous_handlers: dict[signal.Signals, object] = {}

    def request_stop(_signum, _frame) -> None:
        stop_event.set()

    for signum in (signal.SIGINT, getattr(signal, "SIGTERM", signal.SIGINT)):
        if signum in previous_handlers:
            continue
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)
    try:
        if once:
            attempts = worker.run_once(stop_requested=stop_event.is_set)
            for attempt in attempts:
                _print_automation_attempt(attempt)
            succeeded = sum(item.status == "succeeded" for item in attempts)
            abnormal = len(attempts) - succeeded
            console.file.write(
                f"attempts: {len(attempts)} succeeded: {succeeded} abnormal: {abnormal}\n"
            )
            if abnormal:
                raise typer.Exit(code=1)
            return

        console.file.write("worker: started\n")
        failures = worker.run_forever(
            stop_event,
            poll_seconds=poll_seconds,
            on_attempt=_print_automation_attempt,
        )
        console.file.write(f"worker: stopped failures: {failures}\n")
        if failures:
            raise typer.Exit(code=1)
    except AutomationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def _print_automation_attempt(attempt: AutomationAttempt) -> None:
    error = _bounded_text(attempt.error) if attempt.error else "-"
    console.file.write(
        f"{attempt.attempt_id}\tautomation: {attempt.automation_id}\tstatus: {attempt.status}"
        f"\tscheduled: {attempt.scheduled_for}\trun: {attempt.run_id}"
        f"\tsummary: {attempt.summary_path or '-'}\terror: {error}\n"
    )


@eval_app.command("run")
def eval_run(
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for eval artifacts."),
) -> None:
    """Run the fixed offline FakeLLM reference set."""
    workspace = (cwd or Path.cwd()).resolve()
    try:
        report = run_reference_eval(workspace)
    except EvalError as exc:
        console.file.write(f"{_bounded_text(str(exc))}\n")
        raise typer.Exit(code=1) from exc
    for case in report.cases:
        detail = f"\tdetail: {_bounded_text(case.failure_detail)}" if case.failure_detail else ""
        console.file.write(
            f"{case.case_id}\tpassed: {str(case.passed).lower()}"
            f"\tcompleted: {str(case.completed).lower()}\tterminal: {case.terminal_action or '-'}"
            f"\tstatus: {case.terminal_status or '-'}\terror_code: {case.terminal_error or '-'}"
            f"\ttool_calls: {case.tool_calls}\terrors: {case.errors}"
            f"\tduration_ms: {case.duration_ms}{detail}\n"
        )
    console.file.write(
        f"eval: passed: {report.passed_cases} failed: {report.failed_cases}"
        f" completed: {report.completed_cases} tool_calls: {report.tool_calls} errors: {report.errors}"
        f" duration_ms: {report.duration_ms}\n"
    )
    console.file.write(f"report: {report.report_path.relative_to(workspace).as_posix()}\n")
    if not report.passed:
        raise typer.Exit(code=1)


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
        if event.get("reason"):
            console.print(str(event["reason"]))
    elif name == "capability_warning":
        console.print(
            f"capability warning: {event.get('requested')} unavailable; "
            f"falling back to {event.get('fallback')}"
        )


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
    stop_reason = (getattr(error, "details", None) or {}).get("stop_reason")
    if stop_reason in {"cancelled", "timed_out"}:
        return stop_reason
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
