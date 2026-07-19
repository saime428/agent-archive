# 设计：MCP Server 故障隔离与空参数兼容

- 日期：2026-07-18
- 状态：已确认，待实施
- 实施计划：[2026-07-18-mcp-server-fault-isolation.md](../plans/2026-07-18-mcp-server-fault-isolation.md)
- 上位设计：[stdio MCP 动态工具集成](2026-07-17-stdio-mcp-dynamic-tools-design.md)

## 背景

当前 `McpStdioRuntime` 在任意已启动 Server 的请求超时或 owner 退出后，会把共享 Runtime 标记为 `failed` 并关闭全部 owner。Workbench 和 CLI chat 复用同一个 Runtime，因此一次局部故障会让之后的所有 turn 在 `discover_tools()` 阶段失败，连内置工具也无法继续使用。

另外，部分 OpenAI-compatible 服务会把无参数工具调用编码为 `arguments: ""`。当前 adapter 将它当成畸形 JSON，触发一次没有必要的模型 repair。

已建立两个确定性复现：

- 两台真实 stdio fixture Server 中，一台调用超时后，另一台健康 Server 当前也无法继续调用。
- `_envelope_from_tool_message()` 收到空 `arguments` 时返回空字符串，而不是带空对象参数的 action envelope。

## 目标

1. Runtime 已进入 `ready` 后，单个 Server 的 request timeout、EOF、进程退出或协议/transport 故障只淘汰该 Server。
2. 故障 Server 的定义与 Target 从后续快照中原子移除；旧 Target 立即失败，不再路由远端调用。
3. 其他 MCP Server 和内置工具继续可用；全部 MCP Server 都失效时，后续 turn 使用纯内置 Tool Catalog。
4. 超时调用仍只报告一次 `TIMEOUT`，绝不自动重放、重连或重启 Server。
5. 空白 `arguments` 兼容为 `{}`；非空畸形 JSON 继续进入现有 repair 路径。

## 状态与故障边界

Runtime 的公开状态机仍为：

```text
new -> starting -> ready -> closing -> closed
                 \-> failed
```

不新增第二套 Runtime 状态机。`_dead_servers` 继续记录 Server 级终态，规则如下：

- `starting` 期间任一 Server 失败：保持首次 discovery 全有或全无，Runtime 进入 `failed` 并关闭全部进程。
- `ready` 后单个 owner 结束：把 Server 加入 `_dead_servers`，移除它的快照和已知 Target，重新组合 `_snapshot`；Runtime 保持 `ready`。
- 已开始的 request timeout：先按上述规则淘汰 Server，再只取消对应 owner，并等待最多现有 close 宽限。
- 单 Server owner 无法在宽限内退出，或共享事件循环/线程本身失败：升级为 Runtime 级 `failed`，执行现有全局关闭，避免遗留不确定后台请求。
- refresh 中 Server transport/protocol 失败：淘汰该 Server并返回剩余 last-good 快照；其他 dirty Server 可在后续 discovery 继续刷新。
- refresh 的本地 metadata 安全错误仍保留现有 fail-closed 行为，不把不安全的新快照发布给模型。

## 快照不变量

- `_server_snapshots` 不再包含故障 Server。
- `_snapshot` 始终由存活 Server 的 `_server_snapshots` 按冻结配置顺序组合。
- `_known_targets` 只移除故障 Server 的 Target；其他 Server 的旧 Target 仍可服务已经开始的 run。
- `_mark_dirty()` 忽略已经淘汰的 Server，禁止死亡 owner 重新进入刷新队列。
- 配置快照不热重载，Runtime 内不重新启动 Server。

## OpenAI-compatible 空参数

仅当 `function.arguments` 是空字符串或只含空白时，把它作为字符串 `"{}"` 解析。这样无参数 Tool 可以直接通过 schema 校验；需要字段的 Tool 会得到现有 `MISSING_REQUIRED_FIELD` repair，而不是先得到无上下文的 `INVALID_JSON`。

非字符串参数、非对象 JSON 和非空畸形 JSON 的现有行为不变。

## 非目标

- 自动 reconnect、restart、重试或调用重放。
- 新 MCP 健康页面、事件类型、配置项或后台探活。
- 修改 validator 指纹校验；它继续防止 Runtime 发布后 validator contract 被篡改。
- 拆分 `mcp_runtime.py`、新增依赖或重写 Tool Catalog。

## 验收

- 双 Server 集成测试证明：一台 request timeout/退出后，另一台仍能调用且下一次 discovery 只返回健康 Server。
- 单 Server 失效后 discovery 返回空 tuple，内置 catalog 可继续构建。
- 超时 Server 调用次数仍为 1，旧 Target 后续快速失败。
- owner 无法停止时仍升级为 Runtime 失败。
- 同步与流式 OpenAI-compatible 路径都把空参数归一化为 `{}`；非空畸形 JSON 仍进入 repair。
- Windows 开发者模式相关 symlink/junction 用例全部实际运行，不再跳过。
- 聚焦测试与全量 pytest 通过，工作区无测试进程残留。
