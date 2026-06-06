from __future__ import annotations

import platform
from pathlib import Path

import typer
from rich.console import Console

from agent.core.loop import run_once
from agent.core.run_store import RunStore, RunStoreError
from agent.llm.fake import FakeLLMClient

app = typer.Typer(help="Minimal Python CLI agent.")
runs_app = typer.Typer(help="Inspect agent run logs.")
app.add_typer(runs_app, name="runs")
console = Console()


@app.callback()
def _root() -> None:
    """Minimal Python CLI agent."""


@app.command()
def doctor() -> None:
    """Report the minimal local environment status."""
    console.print(f"Python: {platform.python_version()}")
    console.print(f"cwd: {Path.cwd()}")
    console.print("agent import: ok")


@app.command()
def run(task: str) -> None:
    """Run an agent task."""
    result = run_once(task, FakeLLMClient())
    final = (result.observation.data or {}).get("final", "")
    console.print(f"run_id: {result.context.run_id}")
    console.print(f"final: {final}")
    console.print(f"summary: {result.summary_path}")


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
