# Frontend vNext 阶段 2 验收记录

- 日期：2026-07-25
- 范围：阶段 2 核心功能等价（F1-F5、R1-R8、H3-H7、S3-S4）
- 计划：[`2026-07-24-frontend-vnext-phase2-functional-parity.md`](../superpowers/plans/2026-07-24-frontend-vnext-phase2-functional-parity.md)
- 结论：阶段 2 功能等价达成。**未**切换默认入口、**未**删除旧静态 Workbench。
  这不代表 Frontend vNext 长期路线完成（Monaco、真实 terminal、Git 工作区、
  生态中心属于阶段 3-5）。

## 1. 真实服务验收

不使用 mock。构建产物由现有 Python Workbench 同源提供。

- 构建：`npm run build:preview` → `src/agent/web/static/preview/`（产物不入 git）
- 服务：`agent ui --cwd D:\CodexScratch\phase2-acceptance --port 8766`
- **专用临时 workspace**，仓库配置与文件未被本次验收修改

### 入口并存

| 入口 | 结果 |
| --- | --- |
| `/preview/` | 200，React 工作台，CSP `default-src 'self'` 未放宽 |
| `/` | 200，仍是旧静态 Workbench（默认入口未切换） |

### 文件闭环（F1-F5）

| 项 | 证据 |
| --- | --- |
| F1 目录浏览 | `/api/files` → `path=.`，entries `src`、`README.md` |
| F2 文件预览 | `/api/file?path=README.md` → `truncated=false`、`size=63`、真实正文 |
| F3 保存 | `run_20260725_102926_244437`、`bytes_written=69`、snapshot 落于 `.agent/runs/<run>/snapshots/act_000001/original`；磁盘内容确认已改写 |
| F4 diff | `current_exists=true`、`snapshot_missing=false`，返回真实 unified diff（含 BOM 行差异） |
| F5 恢复 | `action=restored`；磁盘内容确认回到 `original line two` |

保存**确实**经过 sandbox 路径策略、创建 snapshot 并记录 run —— 与旧前端语义一致，
且不进入 chat approval 队列（浏览器侧的显式确认是 UI 保护，不冒充后端审批）。

### 运行与复盘（R1-R8）

| 项 | 证据 |
| --- | --- |
| R1 | `/api/runs` 返回 1 条真实 run，含 `status=ok`、`risk_level=medium` |
| R2-R7 | detail 顶层键齐全：`summary/tool_calls/snapshots/review/workflow/failure/patch_review/recovery/replay`；`review.changed_files=README.md`、`snapshot_count=1`、`patch_review.risk_level=medium`、`recovery.rollback_available=true`、`replay.step_count=1` |
| R3 | `workflow.verification_commands` = `python -m pytest tests/test_docs.py -q`、`git diff --check`（仅展示与复制，浏览器不执行） |
| R8 | trace/replay 的文本与终态过滤为前端本地过滤，E2E 覆盖 |

### 健康与设置（H3-H7）

| 项 | 证据 |
| --- | --- |
| H3 | `settings_readiness.status=ready`、`mode=read-only`、checks 可读 |
| H4 | `workspace_risk.risk_level=medium`、`signals.snapshots=1` |
| H5 | `memory_review.mode=read-only`、pending/active 计数；界面无 accept/reject 动作 |
| H6 | `POST /api/config {mode:"auto"}` → `status=ok`；落盘 `.agent/config.toml` **仅含** `mode = "auto"`（原子写、只发变化键） |
| H7 | `/api/tools` → 16 个工具，只读展示 |

### 安全边界（真实拒绝）

| 尝试 | 结果 |
| --- | --- |
| `approval = never` | **400** `browser config cannot disable approvals.` |
| `sandbox = danger-full-access` | **400** `sandbox must be read-only or workspace-write.` |
| 越界路径 `../../etc/passwd` | **400** |

前端不提供密钥输入框；`base_url`、`allowed_commands` 只读展示，不在写白名单内。

## 2. 自动门禁

| 门禁 | 结果 |
| --- | --- |
| `npm ci` | 干净安装，0 vulnerabilities |
| `npm run check` | **41 passed**（typecheck + lint + check:ui + vitest + build + Playwright） |
| `pytest -q`（全量） | **1030 passed** |
| `git diff --check` | 通过 |

`check:ui` 持续报告 Lucide-only、产品界面零 emoji、零手写 SVG。

## 3. 视觉基线

10 张确定性快照（刷新时间戳已 mask）：

- 阶段 1 壳：`a-dark-desktop`、`b-dark-desktop`、`b-light-desktop`、`b-dark-mobile-390`、`b-dark-mobile-320`、`c-light-desktop`
- 阶段 2 工作台：`workspace-system-dark-1440`（System readiness）、`workspace-files-light-1440`（Files 编辑态）、`workspace-runs-dark-390`（Run attention）、`workspace-system-dark-320`

E2E fixture 已改为**真实长度数据**（长会话标题、`run_20260725_045603_309947` 式 run id、
多行 summary）——短 fixture 正是早期没能测出列溢出的原因。

## 4. 性能

| 指标 | 结果 | 预算 |
| --- | --- | --- |
| 30 秒流式 fps | **59.31** | ≥ 55 |
| 30 秒流式 long task | **0 个** | 最长 < 200ms |
| 工作台开启 + run 过滤 + 视图切换 | 最长 long task **< 100ms** | < 100ms |

## 5. 可访问性与响应式

- 全键盘链路：Enter 开面板 → 切三视图 → 打开 run detail → Escape 关闭且焦点回到触发按钮
- 工作台内每个按钮均有可访问名（自动扫描 0 例外）
- 1440 / 390 / 320 三视口下 System→Files→Runs+diff 全程无横向溢出
- 长 Windows 路径与长 run id 省略显示并保留 `title`
- 确认对话框（保存 / 丢弃 / 恢复 / 关闭守卫）统一走 Radix Dialog，具备焦点陷阱与 Escape
- reduced-motion 下无 spring 位移，Canvas 保持静态，状态文字不减少

## 6. 已知限制

1. **人工视觉审查未在真实可见浏览器完成。** 本次可用的浏览器面板不合成帧
   （`visibilityState=hidden`、`requestAnimationFrame` 不触发），motion 入场动画与
   `mode="wait"` 视图切换在该环境下无法目视确认；已通过 Playwright（正常合成）与
   代码审查覆盖。**建议在真实浏览器补一次人工观感确认。**
2. `diff`、`restore`、`file/save` 未加 Python 侧契约测试（构造真实 snapshot 成本较高），
   由本次真实服务验收覆盖；后端若改这些字段，前端不会自动变红。
3. 视觉评分仅为内部设计代理判断，**不代表** Awwwards / FWA / CSS Design Awards 的
   任何真实评审结果或获奖。
4. 递归 workspace 搜索、Monaco、真实 terminal、Git 工作区、生态管理生命周期均未实现，
   属后续阶段。

## 7. Rollback

阶段 2 全部改动局限在 `frontend/` 与 `src/agent/web/static/preview/`（后者不入 git）：

- 回退前端：`git revert` 相关提交，或直接删除 `frontend/` 与 staged preview 目录
- 旧静态 Workbench 未被修改，`/` 始终可用，是随时可回退的基线
- 后端 HTTP/SSE schema、sandbox、snapshot、run store、config write 本阶段**零改动**

## 8. 下一步

阶段 2 的结论仅为「**默认入口切换准备就绪**」。切换 `agent start` 根入口、
观察稳定期、删除旧静态壳属于后续独立计划，需要用户再次明确授权。
