from __future__ import annotations

import platform
from pathlib import Path

import typer
from rich.console import Console

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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
