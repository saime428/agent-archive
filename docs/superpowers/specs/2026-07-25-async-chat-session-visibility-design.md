# 设计：异步新会话在返回前可读取

- 日期：2026-07-25
- 状态：已实施并验收
- 触发来源：Frontend vNext Default Entry Cutover 实服 E2E
- 上位约束：[Project vNext 总方向](../../project-vnext-direction.md)

## 问题与证据

真实 Python 服务中，`POST /api/chat/start` 返回新 `session_id` 后，React 会立即读取
`GET /api/chats/<session_id>`。失败 trace 对同一会话记录了：

1. 首次详情请求返回 500，响应为 `session.json` 不存在；
2. 约 23ms 后第二次请求返回 200；
3. 后台 turn 完成后文件存在，说明不是路径错误或清理错误。

根因是 `ChatRuntime.start()` 只在内存中创建 `ConversationState`，先启动后台 worker 并
返回 ID；`ChatSession.run_turn()` 直到 turn 完成才首次保存会话。公开 ID 与持久状态之间
因此存在可重复的读取窗口。

## Interface 合同

`ChatRuntime.start()` 成功返回时，其 `session_id` 必须已经能被现有 chat detail
Interface 读取。后台 turn 尚未完成时，详情是合法的空会话（`turn_count == 0`），而不是
500、重试约定或前端忽略的错误。

该合同同时适用于自动生成 ID 和调用者提供但尚不存在的合法 ID。已有会话不增加无意义的
预写；turn 完成后仍由 `ChatSession.run_turn()` 保存最终状态。

## 最小实现

在 `ChatRuntime.start()` 已加载或创建 state、且已取得当前进程内 session claim 后：

1. 用既有 state 路径判断 `session.json` 是否已存在；
2. 仅在不存在时调用既有 `ConversationState.save(config)`；
3. 保存成功后才创建并启动后台 job。

`save()` 已复用路径重定向校验、redaction、临时文件、`fsync` 与 `os.replace` 原子发布；
不新增 store、锁、重试、sleep 或前端容错分支。保存失败沿现有 `start()` 异常路径释放
session claim，且不会启动 worker。

## 范围

- `src/agent/web/chat_runtime.py`
- `tests/test_web.py`
- `CHANGELOG.md`
- Cutover 验收记录
- 本 spec 与对应 implementation plan

不修改 HTTP/SSE schema、React 源码、ConversationState 文件格式、session ID 规则、
approval/sandbox/redaction 或静态入口映射。

## 验收

- 用阻塞 LLM 固定“start 已返回、turn 尚未保存”的窗口；自动 ID 与显式新 ID 均能读取
  `turn_count == 0`，测试在修复前稳定得到 `FileNotFoundError`；
- `tests/test_web.py` 全部通过；
- 原始实服 E2E 无 4xx/5xx、request failure 或 console error；
- 至少 5 个全新隔离服务连续通过原始 E2E；
- 五轴审查确认只有缺失文件分支增加一次原子写，已有会话无额外写入。

## 设计审查

- 正确性：在 ID 暴露前建立持久状态，直接消除读取窗口；不靠重试掩盖。
- 可读性：两行条件写入位于 lifecycle composition root，无新 helper 或抽象。
- 架构：继续复用 `ConversationState.save()` 这一深 Module；chat detail Interface 不变。
- 安全：路径校验、脱敏和原子发布全部复用，未扩大输入或文件权限。
- 性能：只给尚未持久化的新会话增加一次小文件写；已有会话不重复预写。
- 结论：通过，无未解决 finding。
