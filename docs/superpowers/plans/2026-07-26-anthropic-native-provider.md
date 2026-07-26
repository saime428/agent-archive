# Anthropic 原生 Provider 实施计划

- 日期：2026-07-26
- 对应设计：`docs/superpowers/specs/2026-07-26-anthropic-native-provider-design.md`

## 任务

1. `src/agent/llm/anthropic.py`：`AnthropicClient`（chat + stream_chat +
   消息转换 + SSE 解析）与 `smoke_anthropic_provider`，复用 openai_compat
   的传输/重试/错误原语。
2. `src/agent/config.py`：provider 枚举加 `"anthropic"`。
3. `src/agent/llm/factory.py`：`_make_anthropic`、`_smoke_anthropic`、
   注册表条目。
4. `src/agent/web/settings.py`：provider 错误文案补 `anthropic`。
5. `tests/test_anthropic.py`：假 transport 单测（映射/重试/流式/smoke）；
   `tests/test_llm_factory.py` 补 factory 与能力断言。
6. `README.md` 配置示例、`CHANGELOG.md` 条目。
7. 全量 pytest + 前端门禁复跑，提交推送，CI 绿。
