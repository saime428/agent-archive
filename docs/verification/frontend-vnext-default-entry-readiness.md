# Frontend vNext 默认入口切换 Readiness 验收记录

- 日期：2026-07-25
- 范围：只完成 Readiness；不切换根 `/`，不删除旧 Workbench
- 设计：[`2026-07-25-frontend-vnext-default-entry-cutover-readiness-design.md`](../superpowers/specs/2026-07-25-frontend-vnext-default-entry-cutover-readiness-design.md)
- 计划：[`2026-07-25-frontend-vnext-default-entry-readiness.md`](../superpowers/plans/2026-07-25-frontend-vnext-default-entry-readiness.md)
- 结论：Frontend vNext 默认入口切换就绪。根 `/` 仍返回旧 Workbench，Cutover 仍需再次明确授权。

## 1. 范围与入口矩阵

未修改 CLI、HTTP/SSE API、前端业务源码、Vite `base`、运行时配置或依赖，也未创建
feature flag 或第二份 bundle。

| URL | 状态 | 文档 | 缓存 |
| --- | --- | --- | --- |
| `/` | 200 | 旧 `index.html` | `no-store` |
| `/preview/` | 200 | React `preview/index.html` | `no-store` |
| `/legacy/` | 200 | 旧 `index.html` | `no-store` |
| `/preview?manual=1` | 308 | `/preview/?manual=1` | - |
| `/legacy?manual=1` | 308 | `/legacy/?manual=1` | - |

非 HTML 哈希资源未被统一设置为 `no-store`。

## 2. Git bundle 与 Python HTTP

- `.gitignore` 仅移除 `src/agent/web/static/preview/` 忽略规则；`frontend/dist/` 继续忽略。
- `.gitattributes` 对 `frontend/index.html` 与 preview 文件树设置 `-text`，阻止 Windows
  checkout 改写 Vite HTML 输入和 bundle 字节。
- `npm run build:preview` 生成 14 个运行时文件；候选 Git tree 包含完整文件树。
- Python handler 逐文件返回的字节与磁盘源文件一致；缺失 preview 目录返回 404。
- `tests/test_web.py tests/test_docs.py`：**133 passed**。
- Python 全量：**1038 passed**。

## 3. Python 实服与 wrapper

- `node --test scripts/start-served-workbench.test.mjs`：**4 passed，1 skipped**。
- [Node `child_process` 文档](https://nodejs.org/api/child_process.html#subprocesskillsignal)
  说明 Windows 的 `SIGTERM`/`SIGKILL` 是强制终止语义，因此 served teardown 使用显式
  `stop`/`done` 控制握手；POSIX 信号转发用例在 Windows 明确跳过。该握手属于本项目测试
  harness，不是 Vite 或 Playwright 的协议。
- 自动化覆盖 4174 已占用快速失败、跨 stderr chunk 的 4175 退让检测、非零退出码传播、
  临时 HOME/USERPROFILE 隔离、子进程退出、临时目录删除与 4174/4175 端口释放。
- `npm run test:e2e:served`：**1 passed**；`/api/health` 为 200，`Server` 头以
  `AgentWorkbench/` 开头，`/preview/` 无失败请求、loopback 4xx/5xx 或 console error。

## 4. Wheel 内容闭包

在 `D:\CodexScratch` 唯一临时目录中执行 `pip wheel . --no-deps`，未使用
`--no-build-isolation`。生成 `agent-2.1.0-py3-none-any.whl`：

- wheel preview 路径数：14；
- 源码与 wheel 路径集合相等；
- 14 个同名文件逐字节相等；
- wheel 大小：477221 bytes；
- SHA-256：`f4ff9f5ad7597a23a61d23e306ff3015e1448a499878516d3b5b7ec93d065216`。

## 5. 候选 tree object 与重建

使用从 `HEAD` 初始化的独立 `GIT_INDEX_FILE`，只加入批准文件；真实 index 保持为空。
由该 index 创建临时 tree/commit object 和 D 盘 detached worktree，不移动当前分支：

- 不执行 npm 时，新旧两个 `index.html` 均存在；
- `npm ci` 后执行 `npm run build:preview`；
- `git status --porcelain=v1 --untracked-files=all -- src/agent/web/static/preview` 无输出；
- detached worktree 与本次临时目录均已删除。

这是“候选 tree object 验证”，不是正式提交后的 clean checkout 证据。获准提交后仍需从
真实提交重新执行一次。

## 6. 全量门禁

| 门禁 | 结果 |
| --- | --- |
| `npm run check` | typecheck、lint、UI policy、17 个 Vitest、41 个 Playwright 通过；1 个性能采样用例按设计跳过 |
| `pytest -q` | 1038 passed |
| `agent release doctor --cwd <repository>` | `release readiness: complete` |
| `git diff --check` | 通过 |
| 依赖与范围 | 无新增依赖；无 `frontend/src/**`、CLI、配置键或计划外生产改动 |

计划列出的 `/ccg:verify-change` 与 `/ccg:verify-quality` 在当前工具清单及仓库中均未提供，
因此未声称运行；本次以五轴代码审查、HTTP/进程/文件清理安全复核及上述全量门禁替代。

## 7. 可见浏览器

真实 Python Workbench 使用隔离 workspace/home 和 4174 端口：

- `/preview/` 加载 React Workbench，Files、Runs、System 均可打开；
- `/legacy/` 与 `/` 均显示旧 Workbench；
- 两个无尾斜杠入口均保留 `manual=1` 查询字符串；
- 浏览器 warning/error 为 0。

验收关闭期间发现客户端主动断开会触发服务端重复写 500 的 traceback；已在 GET/POST
共享 handler 边界忽略 BrokenPipe/ConnectionReset/ConnectionAborted，并增加回归测试。

## 8. Rollback 与完成声明

Rollback 不需要重建：恢复根入口映射并重启服务即可；当前根入口本来就仍是旧
Workbench。旧资源、`/preview/`、`/legacy/`、会话、run、snapshot、config 和 memory
均未删除或迁移。

本记录只证明 Readiness。默认入口仍未切换，后续 Cutover 必须再次获得明确授权。
