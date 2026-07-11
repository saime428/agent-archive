# Changelog

## Unreleased

- 错误恢复:可恢复的工具错误(TOOL_FAILED/TIMEOUT/SANDBOX_VIOLATION/INVALID_ARGUMENT/POLICY_DENIED)回喂模型自我纠正,新增 `max_consecutive_errors` 配置(默认 3),连续错误耗尽预算才终止;写操作成功结果同样回喂;迭代预算剩 2 次时提醒模型收尾。
- 移除 run loop 中的中文关键词短路(`_direct_chat_answer` / `_direct_external_list_path`),所有输入统一走模型路径。
- Provider 泛化:新增 `openai-compat` provider(可配 `base_url` / `api_key_env`,api key 可空),DeepSeek 变为薄预设层,现有配置零破坏;可直接接入 Ollama/vLLM 等本地 OpenAI 兼容端点。
- 原生 function calling:`native_tools = true` 时 deepseek/openai-compat 走原生工具调用(含流式分片拼装),所有动作皆工具、每轮恰好一个;JSON 协议保留为 fallback,fake provider 自动回落。

## 2.1.0 - 2026-07-08

- 安全硬化：保护 `.agent/` 内部状态写入，收敛 Workbench 动态 HTML 注入面，并清理过期 SSE 聊天任务。
- 工程整理：同步项目版本、建立变更日志、清理重复文档和过时路线图表格。
