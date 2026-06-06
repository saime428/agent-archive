from __future__ import annotations

import platform
import shutil
from pathlib import Path

import typer
from rich.console import Console

from agent.config import ConfigError, ConfigOverrides, load_config
from agent.core.loop import run_once
from agent.core.run_store import RunStore, RunStoreError
from agent.llm.fake import FakeLLMClient
from agent.policy.approvals import CONFIRMATION_REQUIRED_ACTIONS, LOW_RISK_ACTIONS

app = typer.Typer(help="Minimal Python CLI agent.")
runs_app = typer.Typer(help="Inspect agent run logs.")
tools_app = typer.Typer(help="Inspect available agent tools.")
config_app = typer.Typer(help="Inspect agent configuration.")
app.add_typer(runs_app, name="runs")
app.add_typer(tools_app, name="tools")
app.add_typer(config_app, name="config")
console = Console(highlight=False)


TOOL_DESCRIPTIONS = {
    "done": "Finish the run with a final response.",
    "list_dir": "List workspace directory entries.",
    "read_file": "Read a workspace text file.",
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
    try:
        config, diagnostics = load_config(Path.cwd())
    except ConfigError as exc:
        console.print(f"config error: {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"Python: {platform.python_version()}")
    console.print(f"cwd: {Path.cwd()}")
    console.print("agent import: ok")
    console.print(f"rg available: {str(shutil.which('rg') is not None).lower()}")
    console.print(f"config mode: {config.mode}")
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
            ),
        )
    except ConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    result = run_once(task, FakeLLMClient(), cwd=workspace, config=config)
    final = (result.observation.data or {}).get("final", "")
    console.print(f"run_id: {result.context.run_id}")
    console.print(f"mode: {config.mode}")
    console.print(f"sandbox: {config.sandbox}")
    console.print(f"approval: {config.approval}")
    console.print(f"dry_run: {str(config.dry_run).lower()}")
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


def _tool_category(tool_name: str) -> str:
    if tool_name == "done":
        return "terminal"
    if tool_name in LOW_RISK_ACTIONS:
        return "low-risk"
    if tool_name in CONFIRMATION_REQUIRED_ACTIONS:
        return "confirmation-required"
    return "unknown"


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
