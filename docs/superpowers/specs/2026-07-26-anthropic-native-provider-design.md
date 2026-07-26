# Anthropic 原生 Provider 设计

- 日期：2026-07-26
- 状态：用户已批准范围（仅 Anthropic 原生 + 仅 JSON 协议切片），实施中
- 范围外：Gemini 原生协议、native tools（chat_tools/stream_chat_tools）、按需再开切片

## 背景

现有 `openai-compat` provider 只覆盖 OpenAI 兼容端点。部分中转站/端点只提供
Anthropic 原生 `/v1/messages` 协议，需要一个原生适配器。

## 目标

新增 `provider = "anthropic"`：

- `chat()` + `stream_chat()`，走项目现有 JSON 文本动作协议（模型以文本返回动作
  JSON，loop 负责解析与 repair），与 loop 零改动兼容。
- `capabilities = ProviderCapabilities(streaming=True, native_tools=False)`。
  `native_tools = true` 时按现有能力声明机制发 `capability_warning` 并降级。
- `agent provider smoke anthropic` 支持连通性冒烟；`--native` 明确报错。

## 协议映射

- URL：`{base_url}/v1/messages`；`base_url` 默认 `https://api.anthropic.com`，
  中转站填其源站（不带 `/v1`）。
- 头：`anthropic-version: 2023-06-01`；key 非空时发 `x-api-key`（空 key 不发头，
  与 openai-compat 对本地/免鉴权端点的容忍一致）。key 从通用 `api_key_env`
  指到的环境变量读取（建议 `ANTHROPIC_API_KEY`）。
- 请求体：`model`、必填 `max_tokens`（默认 8192）、`messages`、可选 `system`、
  可选 `temperature`。
- 消息转换：内部 `system` 消息合并进 `system` 参数；Anthropic 要求 user/assistant
  严格交替，连续同角色消息用空行合并。
- 响应：拼接 `content[]` 中全部 `text` 块；与 `_parse_chat_response` 相同的
  尾部行为——整体可解析为 JSON 对象则返回 dict，否则返回原文本。
- 流式：SSE 事件按 `data:` 载荷的 `type` 判定：`content_block_delta` 且
  `delta.type == "text_delta"` 产出文本；`message_stop` 结束；`error` 抛
  `ProviderError`；其余（`ping`/`message_start`/`content_block_*`/`message_delta`）
  忽略。`event:` 行忽略（信息已含于 data 载荷）。

## 复用（Ponytail 阶梯）

复用 `openai_compat` 的 `ProviderError`、`SmokeResult`、`Transport`/
`StreamTransport`/`RetrySleep` 类型、`_ReusableHTTPTransport`（含本轮修复的
错误响应排干与异常映射）、`_retry_transient`、`_is_retryable_http`，以及
smoke 的 `parse_model_action` 验证流程。不新增依赖、不新建传输层。

## 配置面

- `config.py` provider 枚举加 `"anthropic"`；复用现有 `base_url` / `api_key_env`
  字段，不新增配置键。
- factory 注册 `ProviderSpec`：`api_key_required=False`、`requires_base_url=False`
  （空则用官方默认）。
- `web/settings.py` 校验走 `PROVIDER_REGISTRY` 成员自动放行，仅更新错误文案。

## 验收

- 单测覆盖：URL/头/请求体映射（含 system 合并与同角色合并）、空 key 不发头、
  429 重试、流式解析（增量文本/结束/错误）、smoke 成功路径、factory 构造与
  能力声明、默认 base_url。
- 全量 pytest + 前端门禁不回归；README 配置示例 + CHANGELOG 记录。
