# 异步新会话可见性修复计划

- 日期：2026-07-25
- 状态：已执行
- 设计：[异步新会话在返回前可读取](../specs/2026-07-25-async-chat-session-visibility-design.md)

## Task 1：锁定回归

在 `tests/test_web.py` 用 `threading.Event` 阻塞 LLM，使 `ChatRuntime.start()` 已返回但
worker 尚不能完成。立即通过现有 chat payload builder 读取返回的 session，断言
`turn_count == 0`；参数覆盖自动 ID 与显式合法新 ID。

红灯必须是缺失 `session.json`，不是超时或其他错误。`finally` 始终释放 worker 并等待
job 结束，测试不泄漏线程。

## Task 2：修复唯一生命周期 seam

在 `ChatRuntime.start()` 中，仅当 state 对应的 `session.json` 尚不存在时，调用既有
`state.save(config)`，位置在 session claim 之后、job 创建和 worker 启动之前。

不新增依赖、重试、sleep、前端忽略规则、文件格式或公开 Interface。

## Task 3：回归与原始复现

依次运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web.py -q --basetemp <D盘唯一目录>\pytest
Set-Location frontend
npm run test:e2e:served
Set-Location ..
```

再以 5 个全新 D 盘 workspace/home 独立启动服务，连续执行实服 E2E。每次都要求 chat
详情无 4xx/5xx、request failure 或 console error，并确认 4174 和临时目录已清理。

## Task 4：审查、记录与独立提交

按正确性、可读性、架构、安全、性能五轴审查 diff；更新 CHANGELOG 与 Cutover 验收记录。
本修复与 Cutover 入口映射分开提交，避免扩大 Cutover 的生产代码范围。

建议提交信息：

```text
fix(web): persist async chat sessions before publishing ids
```

## 实施证据

- 确定性回归在修复前稳定得到缺失 `session.json` 的 `FileNotFoundError`；修复后自动 ID
  与显式新 ID 均通过：**2 passed**。
- `tests/test_web.py`：**96 passed**。
- `tests/test_web.py tests/test_docs.py` 聚焦回归：**138 passed**。
- 原始实服 E2E 修复前连续复现 500；修复后 5 个全新隔离服务连续通过，随后当前实现再
  通过 1 次，均无 chat detail 4xx/5xx、request failure 或 console error。
- 未新增依赖、重试、sleep、前端忽略规则或公开 Interface。

## 计划审查

- 红绿信号直接覆盖真实窗口，且已有实服 E2E 保留端到端保护；
- 修复集中在唯一 lifecycle seam，不在 GET 端点或 React 调用者散布重试；
- 失败清理、D 盘隔离与提交边界明确；
- 结论：通过，无未解决 finding。
