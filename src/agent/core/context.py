from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class RunContext:
    task: str
    cwd: Path
    run_id: str
    created_at: datetime

    @classmethod
    def create(
        cls,
        task: str,
        cwd: Path | None = None,
        run_id: str | None = None,
    ) -> "RunContext":
        created_at = datetime.now(timezone.utc)
        return cls(
            task=task,
            cwd=(cwd or Path.cwd()).resolve(),
            run_id=run_id or _make_run_id(created_at),
            created_at=created_at,
        )


def _make_run_id(created_at: datetime) -> str:
    return f"run_{created_at.strftime('%Y%m%d_%H%M%S_%f')}"
