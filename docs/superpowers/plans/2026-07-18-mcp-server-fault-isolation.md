# 计划：MCP Server 故障隔离与空参数兼容

- 日期：2026-07-18
- 状态：已执行（全部 Task 与门禁完成）
- 设计：[2026-07-18-mcp-server-fault-isolation-design.md](../specs/2026-07-18-mcp-server-fault-isolation-design.md)
- Implementation base：`50a7b0870f4dc21a74c79b5e78b1fae38894f101`

## 实施约束

- 保持首次 discovery 全有或全无；只缩小 `ready` 后故障的爆炸半径。
- 不自动重放、重连或重启 MCP Server。
- 不新增依赖、公开 Runtime 方法、配置项、UI 或健康状态机。
- validator contract 指纹校验保持不变。
- 所有非项目测试产物继续放在 `D:\CodexScratch`。

## Task 1：锁定失败边界

**Files**

- Modify: `tests/test_mcp_runtime.py`
- Modify: `tests/test_openai_compat.py`

先写失败测试：

1. 两台真实 fixture Server 中，`slow` request timeout 后 `healthy` 仍返回 `ok`，下一次 discovery 只包含 `healthy`。
2. 一台 Server owner 意外结束只移除该 Server，不停止健康 owner。
3. 单 Server 失效后 Runtime 保持 `ready` 并返回空快照；旧 Target 快速失败且调用不重放。
4. 模拟单 Server cancel 超过 close 宽限时，Runtime 仍升级为 `failed`。
5. 同步和流式 native tool call 的空 `arguments` 都产生 `args={}`；非空畸形 JSON 仍返回原文供 repair。

聚焦红灯：

```powershell
python -m pytest tests/test_mcp_runtime.py tests/test_openai_compat.py -q
```

## Task 2：实现 Server 级淘汰

**Files**

- Modify: `src/agent/mcp_runtime.py`

最小实现：

1. 增加一个锁内 helper，原子记录 dead Server、移除它的 snapshot/Target 并重建组合快照。
2. `_owner_finished()` 在 `ready` 后调用该 helper，不再设置全局 stop event。
3. request timeout 只调度并等待对应 owner cancel；取消失败才使用现有全局关闭路径。
4. refresh 遇到带 `server_id` 的运行期故障时淘汰该 Server并返回剩余快照；共享 loop 故障仍全局失败。
5. `_mark_dirty()` 忽略 dead Server。

不增加 per-Server class、重连状态或新的线程。

## Task 3：归一化空 arguments

**Files**

- Modify: `src/agent/llm/openai_compat.py`

在 `_envelope_from_tool_message()` 的现有 `json.loads` seam，把空白字符串替换为 `"{}"`。其他失败路径不变。

## Task 4：同步文档并验证

**Files**

- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-07-17-stdio-mcp-dynamic-tools-design.md`
- Amend: 本设计与计划

验证命令：

```powershell
python -m pytest tests/test_mcp_runtime.py tests/test_openai_compat.py tests/core/test_loop_mcp.py tests/core/test_tool_schemas.py -q -rs
python -m pytest -q -rs
python -m agent.cli doctor
git diff --check
```

额外重复运行此前受 Windows symlink/junction 权限影响的 11 个用例，确认开发者模式下 `11 passed`、无 skip。

## 提交边界

1. `docs: plan MCP server fault isolation`
2. `fix: isolate failed MCP servers`

完成后把本 spec/plan 状态更新为“已实施/已执行”，再做最终差异审查和干净工作区检查。

## 执行结果

- Task 1-3 已按设计完成，没有新增依赖、公开配置或重连状态机。
- 聚焦门禁 `190 passed`；Windows 开发者模式相关用例 `11 passed`、无 skip；全量门禁 `777 passed`、无 skip。
- `python -m agent.cli doctor` 与 `git diff --check` 通过；非项目测试产物只写入 `D:\CodexScratch` 并在提交前清理。
