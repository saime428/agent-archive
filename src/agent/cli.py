from __future__ import annotations

import platform
from pathlib import Path

import typer
from rich.console import Console

from agent.core.loop import run_once
from agent.llm.fake import FakeLLMClient

app = typer.Typer(help="Minimal Python CLI agent.")
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
