from __future__ import annotations

from agent.llm.base import ProviderCapabilities, resolve_capabilities
from agent.llm.deepseek import DeepSeekClient
from agent.llm.fake import FakeLLMClient
from agent.llm.openai_compat import OpenAICompatClient


def test_fake_declares_no_capabilities() -> None:
    assert FakeLLMClient.capabilities == ProviderCapabilities(streaming=False, native_tools=False)


def test_openai_compat_declares_adapter_paths() -> None:
    assert OpenAICompatClient.capabilities == ProviderCapabilities(streaming=True, native_tools=True)


def test_deepseek_inherits_openai_compat_capabilities() -> None:
    assert DeepSeekClient.capabilities is OpenAICompatClient.capabilities


def test_resolve_prefers_declared_capabilities() -> None:
    class Declared:
        capabilities = ProviderCapabilities(streaming=True, native_tools=False)

        def chat_tools(self, messages, tools):
            return {}

    assert resolve_capabilities(Declared()) is Declared.capabilities


def test_resolve_derives_from_methods() -> None:
    class NativeOnly:
        def chat(self, messages):
            return {}

        def chat_tools(self, messages, tools):
            return {}

    caps = resolve_capabilities(NativeOnly())
    assert caps == ProviderCapabilities(streaming=False, native_tools=True)


def test_resolve_does_not_treat_native_stream_as_regular_stream() -> None:
    class NativeStreamOnly:
        def chat_tools(self, messages, tools):
            return {}

        def stream_chat_tools(self, messages, tools):
            yield "chunk"

    caps = resolve_capabilities(NativeStreamOnly())
    assert caps.streaming is False
    assert caps.native_tools is True


def test_resolve_ignores_non_capability_attribute() -> None:
    class WrongType:
        capabilities = "streaming"

        def stream_chat(self, messages):
            yield "chunk"

    caps = resolve_capabilities(WrongType())
    assert caps == ProviderCapabilities(streaming=True, native_tools=False)
