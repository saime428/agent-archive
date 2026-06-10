from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

import typer
from rich.console import Console

from agent.config import ConfigError, ConfigOverrides, load_config
from agent.core.loop import run_once
from agent.core.memory import MemoryError, MemoryStore
from agent.core.run_store import RunStore, RunStoreError
from agent.core.skills import SkillError, discover_skills, load_selected_skills
from agent.llm.deepseek import DeepSeekClient, DeepSeekError
from agent.llm.fake import FakeLLMClient
from agent.policy.approvals import CONFIRMATION_REQUIRED_ACTIONS, LOW_RISK_ACTIONS

app = typer.Typer(help="Minimal Python CLI agent.")
runs_app = typer.Typer(help="Inspect agent run logs.")
tools_app = typer.Typer(help="Inspect available agent tools.")
config_app = typer.Typer(help="Inspect agent configuration.")
skills_app = typer.Typer(help="Inspect and load agent skills.")
memory_app = typer.Typer(help="Review and manage agent memory.")
app.add_typer(runs_app, name="runs")
app.add_typer(tools_app, name="tools")
app.add_typer(config_app, name="config")
app.add_typer(skills_app, name="skills")
app.add_typer(memory_app, name="memory")
console = Console(highlight=False)


TOOL_DESCRIPTIONS = {
    "done": "Finish the run with a final response.",
    "ask_user": "Stop and return a structured user question.",
    "list_dir": "List workspace directory entries.",
    "read_file": "Read a workspace text file.",
    "read_pdf": "Extract text from a workspace PDF as untrusted source material.",
    "read_docx": "Extract text from a workspace DOCX as untrusted source material.",
    "read_xlsx": "Extract sheet summaries from a workspace XLSX as untrusted source material.",
    "search_files": "Search workspace paths and text.",
    "write_file": "Write a workspace text file with snapshot protection.",
    "apply_patch": "Apply structured text replacements with snapshots.",
    "run_command": "Run an allowed structured argv command.",
    "git_status": "Show repository status.",
    "git_diff": "Show repository diff.",
}
DRY_RUN_SKIPPED_TOOLS = {"write_file", "apply_patch", "run_command"}


@app.callback()
def _root() -> None:
    """Minimal Python CLI agent."""


@app.command()
def doctor() -> None:
    """Report the minimal local environment status."""
    _print_doctor(Path.cwd())


def _print_doctor(cwd: Path) -> None:
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
    console.print(f"config provider: {config.provider}")
    console.print(f"config model: {config.model}")
    console.print(f"config default_skills: {list(config.default_skills)}")
    console.print(f"deepseek api key env: {config.deepseek_api_key_env}")
    console.print(f"deepseek api key present: {str(bool(os.environ.get(config.deepseek_api_key_env))).lower()}")
    console.print(f"config sandbox: {config.sandbox}")
    console.print(f"config approval: {config.approval}")
    console.print(f"config dry_run: {str(config.dry_run).lower()}")
    console.print(f"config global: {diagnostics.global_config_path}")
    console.print(f"config project: {diagnostics.project_config_path}")
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
    result = run_once(task, llm, cwd=workspace, config=config, selected_skills=selected_skills)
    final = (result.observation.data or {}).get("final", "")
    console.print(f"run_id: {result.context.run_id}")
    console.print(f"mode: {config.mode}")
    console.print(f"sandbox: {config.sandbox}")
    console.print(f"approval: {config.approval}")
    console.print(f"dry_run: {str(config.dry_run).lower()}")
    console.print(f"provider: {config.provider}")
    console.print(f"model: {config.model}")
    console.print(f"skills: {[item.name for item in result.skills]}")
    for warning in diagnostics.warnings:
        console.print(f"config warning: {warning}")
    console.print(f"final: {final}")
    console.print(f"summary: {result.summary_path}", soft_wrap=True)


@tools_app.command("list")
def tools_list() -> None:
    """List available tools and policy categories."""
    for tool_name, description in TOOL_DESCRIPTIONS.items():
        category = _tool_category(tool_name)
        dry_run = "skipped" if tool_name in DRY_RUN_SKIPPED_TOOLS else "executes"
        console.file.write(f"{tool_name}\t{category}\tdry-run: {dry_run}\t{description}\n")


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
    console.print(f"provider: {config.provider}")
    console.print(f"model: {config.model}")
    console.print(f"deepseek_api_key_env: {config.deepseek_api_key_env}")
    console.print(f"default_skills: {list(config.default_skills)}")
    console.print(f"memory_auto_write: {str(config.memory_auto_write).lower()}")
    console.print(f"memory_max_items: {config.memory_max_items}")
    console.print(f"sandbox: {config.sandbox}")
    console.print(f"approval: {config.approval}")
    console.print(f"dry_run: {str(config.dry_run).lower()}")
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


def _tool_category(tool_name: str) -> str:
    if tool_name in {"done", "ask_user"}:
        return "terminal"
    if tool_name in LOW_RISK_ACTIONS:
        return "low-risk"
    if tool_name in CONFIRMATION_REQUIRED_ACTIONS:
        return "confirmation-required"
    return "unknown"


def _make_llm(config):
    if config.provider == "fake":
        return FakeLLMClient()
    api_key = os.environ.get(config.deepseek_api_key_env, "")
    return DeepSeekClient(api_key=api_key, model=config.model)


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
