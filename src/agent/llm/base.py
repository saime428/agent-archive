from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderCapabilities:
    streaming: bool
    native_tools: bool


def resolve_capabilities(llm: object) -> ProviderCapabilities:
    declared = getattr(llm, "capabilities", None)
    if isinstance(declared, ProviderCapabilities):
        return declared
    return ProviderCapabilities(
        streaming=callable(getattr(llm, "stream_chat", None)),
        native_tools=callable(getattr(llm, "chat_tools", None)),
    )


class LLMClient(Protocol):
    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
    ) -> dict | str:
        """Return a model response envelope."""

    def stream_chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
    ):
        """Yield text chunks for a model response envelope."""
