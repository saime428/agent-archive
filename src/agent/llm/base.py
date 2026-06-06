from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
    ) -> dict:
        """Return a model response envelope."""
