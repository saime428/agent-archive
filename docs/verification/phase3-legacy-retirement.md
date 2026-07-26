# Phase 3I Legacy retirement 验收记录

- 日期：2026-07-25
- 状态：3I Legacy retirement 已完成
- 设计：[Phase 3I 设计](../superpowers/specs/2026-07-25-phase3-legacy-retirement-design.md)
- 计划：[Phase 3I 计划](../superpowers/plans/2026-07-25-phase3-legacy-retirement.md)

## 当前结论

3I 已完成并通过独立验收。产品静态树现在只保留 React Workbench：根 `/` 与 `/preview/` 继续使用同一份
已跟踪产物，14 个旧壳文件、`/legacy`、`/legacy/` 和只供旧壳使用的同步 `POST /api/chat/turn` 已删除。
现行 async chat、SSE、审批、恢复、会话、运行记录、安全和数据格式没有改变。

下一步是最终对话、生成、前端、后端/API、CLI、package、真实浏览器与缺陷清零矩阵；本记录只声明 3I
完成，不提前声明 Phase 3 或 Project vNext 核心完成。

## 提交与构建闭包

- 设计提交：`d42a1f8`；最终代码提交：
  `37a655538532579eb2880fb5e14de118bdb43bc1`，tree：
  `3fed21e3989e2bb09f249285b4e286feaa55026d`。
- 固定同一 `SOURCE_DATE_EPOCH` 独立构建两次 wheel，均为
  `agent-2.1.0-py3-none-any.whl`、1,272,236 bytes，SHA-256 均为
  `ac68f9ecbcab33282b6785aeaf9e83d2038a31f1ec5f1ea99edb6bd0b59581eb`。
- wheel 与 detached 源码均只含 30 个 preview 文件、3,751,075 bytes；逐字节 diff 为空，legacy 文件计数为 0。
- detached 重新执行 `build:preview` 后 tracked preview 零漂移；没有新增 dependency，
  `npm audit --audit-level=low` 为 0 漏洞，`release doctor` 返回 `release readiness: complete`。

## Interface 与删除边界

- `GET /`、`GET /preview/` 均返回 React；`GET /preview` 的 query-preserving 308、HTML `no-store`、
  cache/security header、gzip、逐字节资产闭包和未知路径行为均通过既有契约。
- `GET /legacy`、`GET /legacy/`、旧 `GET /assets/app.js` 和 `POST /api/chat/turn` 实服均为 404；没有 redirect、
  tombstone 页面、feature flag 或第二套 runtime。
- 生产源码不再出现 `/legacy/`、`/api/chat/turn`、`build_chat_turn_payload` 或 `_reserve_turn`；Git tracked 和
  wheel inventory 不含 14 个旧壳文件。
- 删除同步 wrapper 后，final payload repair、ask-user、公开 action message 和会话 list/rename/delete 已迁移到
  真实 `ChatRuntime` 或 core chat 覆盖，没有在测试里重建退休实现。
- `load_or_create_chat_state`、`build_chat_turn_response` 和 `_reserve_session` 仍由 async runtime 使用并保留；
  workspace、session、run、snapshot、config、memory 与 job 数据没有迁移或删除。

## 自动化验收

- 主工作树 Python 全量：`1164 passed`；3I web/UI/docs 定向：`228 passed`。
- wheel-site 关闭仓库 `pythonpath` 注入后的隔离全量：`1164 passed`；`agent.__file__` 明确来自 D 盘 wheel-site。
- 主工作树和 detached 前端均通过 typecheck、lint、UI policy、33 个 Vitest、production build 与
  Playwright 59 passed；1 个 30 秒性能录制用例按设计 skipped，14 个视觉基线未更新且全部通过。
- 源码实服和 wheel 实服均为 5/5 passed，覆盖默认 React 入口、Files/Git、真实 Terminal、approval cancel、
  Python 父子进程树停止和服务重启恢复。
- 两个新增 async runtime 回归用例单独 2/2 通过；高负载下曾超时的 Terminal 用例在停止并发后重复 10 次
  10/10 passed，正式全量按既有串行配置执行。

## 可见浏览器

使用 wheel 实服分别打开根与 `/preview/`：根完成一轮真实 FakeLLM 对话并显示 final，命令面板具备 dialog、
heading、active combobox、listbox/option 与 Escape 关闭语义；`/preview/` 仍打开同一 React Workbench。
664×929 可见视口无交互阻塞，浏览器 console warning/error 为 0。实服同时确认 `/api/health` 为 200，
四个退休 URL/API 为 404。

## 验收中修复或排除的问题

1. 首轮主树 Python 全量发现跨语言事件契约仍读取已删除的 `assets/sse.js`；改为比较 React
   `CHAT_EVENT_NAMES` 与 Python loop/runtime 事件，保留真实跨语言契约。
2. detached 使用外部 node_modules Junction 时，Vite 按 realpath 解析字体，导致 14 个视觉快照出现纯构建路径差异；
   改用锁定依赖的真实副本后 59 passed、1 skipped，未更新快照或产品代码。
3. wheel-site 首轮用 Windows `NUL` 作为空 pytest 配置，rootdir 被提升到受保护的 `D:\\WpSystem`；改用 D 盘
   显式最小配置后正常收集，确认不是产品失败。
4. detached Python 与前端并发满载时 Terminal 的 1 秒 timeout 用例一次未在 4 秒内收敛；负载结束后隔离重复
   10/10 通过，正式验收改为串行，未放宽产品 timeout 或断言。

## 临时项与 Git 状态

- 4173–4176 均无 LISTENING；wheel 实服已停止，served wrapper 自有 workspace/home 已清理；主工作树和
  detached tracked diff 均通过检查。
- 本轮 D 盘 detached、node_modules、wheel、cache 和测试输出均为可重建验收材料；按用户清理授权规则暂时
  保留，最终交付时统一列出精确路径、大小和可恢复性后再处理。
- 主工作树只保留两份用户原有的未跟踪 handoff；未修改、未暂存。没有 push、Ready 或 merge。

## 完成检查

- [x] 14 个旧静态文件、legacy 路由、同步 turn 与无调用者代码删除
- [x] 根/preview/async chat、安全、数据和 package Interface 无回归
- [x] 源码/detached/wheel 静态闭包、确定性构建、实服与可见浏览器一致
- [x] 代码提交与验证文档分离；Project vNext 核心继续保持未完成
