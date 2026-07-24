# Frontend vNext Phase 1 验收记录

- 日期：2026-07-24
- 状态：通过，作为 `/preview/` 并行预览交付
- 范围：App Shell + Chat 纵切；旧 `/` Workbench 保持默认入口与回退路径
- Spec：[`../superpowers/specs/2026-07-23-frontend-vnext-phase1-shell-chat-design.md`](../superpowers/specs/2026-07-23-frontend-vnext-phase1-shell-chat-design.md)

## 结论

阶段 1 验收面 C1-C9、H1（精简）、H2、S1、S2、S5 已完成。产品 chrome
统一使用 Lucide，静态与运行时门禁均未发现 emoji、Unicode 图形代替图标、
手写 SVG 或第二图标库。前端通过真实 `/api` 与 SSE Adapter 工作；E2E 的
确定性流使用 route-level transport mock，后端事件名与静态交付由 Python 测试
独立守护，避免维护第二套测试服务器。

## 自动门禁

| 门禁 | 结果 |
| --- | --- |
| `npm run typecheck` | 通过 |
| `npm run lint` | 通过，0 warning |
| `npm run check:ui` | 通过，Lucide-only + product emoji 0 |
| Vitest | 5 files / 10 tests 通过 |
| Playwright 常规套件 | 12 通过，30 秒性能用例按环境变量单独运行 |
| Playwright 性能用例 | 通过；30.001s、平均 58.07 FPS、long task 0、stream chunk 187 |
| Python `tests/test_web.py` | 87 通过，含目录 index、CSP 与 gzip 协商 |
| Python 全量 pytest | 1,025 通过，101.64s（短 D 盘 temp 根隔离重跑） |
| `npm audit` | 0 vulnerabilities |
| `/preview/` | HTTP 200；严格 `script-src 'self'`；JS gzip 136,838 bytes |
| Vite dev proxy | health GET 成功；`chat/start` 与 `chat/approval` 的无副作用失败样本到达后端并返回业务 400，不是 403 |

## 视觉与响应式矩阵

下列基线均已人工复核：无横向滚动、文字/CTA 裁切、假入口或传统固定三栏退化。

- `frontend/e2e/workbench.spec.ts-snapshots/a-dark-desktop-win32.png`
- `frontend/e2e/workbench.spec.ts-snapshots/b-dark-desktop-win32.png`
- `frontend/e2e/workbench.spec.ts-snapshots/b-light-desktop-win32.png`
- `frontend/e2e/workbench.spec.ts-snapshots/b-dark-mobile-390-win32.png`
- `frontend/e2e/workbench.spec.ts-snapshots/b-dark-mobile-320-win32.png`
- `frontend/e2e/workbench.spec.ts-snapshots/c-light-desktop-win32.png`

真实生产预览另在 1280 px、390 px、320 px 下检查；1280 px 的
`clientWidth == scrollWidth == 1280`。reduced-motion 下 Canvas 只保留静态构图，
桌面侧栏 resize 支持拖拽与 Arrow/Home/End，移动端会话轨道改为 modal sheet。

## 性能

Lighthouse 13.4.1 最终结果：

| Profile | Performance | FCP | LCP | TBT | CLS | INP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Mobile simulated | 97 | 1,955 ms | 2,158 ms | 56 ms | 0 | 无交互样本 |
| Desktop | 100 | 445 ms | 559 ms | 0 ms | 0.00178 | 无交互样本 |

INP 不能在无用户交互的 Lighthouse 导航审计中生成，因此不伪造数值；关键交互
由 Playwright 的发送、审批、键盘 resize 与 30 秒性能路径覆盖。移动端首轮未压缩
结果为 Performance 81 / LCP 3,671 ms；增加静态 gzip 协商后达到 spec 门槛。

## 交互与性能证据

重型文件保留在
`D:\CodexScratch\agent-frontend-vnext-phase1-evidence-20260724-0332\`，不进 Git：

| 证据 | 大小 | SHA-256 |
| --- | ---: | --- |
| approve trace | 546,895 B | `b29fa502ab176fa9458c416e3e7881d3fedc2cb75c7851d17051bc87ea19ae98` |
| approve video | 65,281 B | `f604a8a2fd91c214cf1eef47abd20f9ef12987e5622a774c97291dfad9539bc5` |
| deny trace | 506,952 B | `a2b54b26ed487fb701bbe95af9674ff780898245b6af93b91f7fabacf25ce9cc` |
| deny video | 57,184 B | `cd3cd80db377523c266646786cd9df794dc773a2edc2b8aaa9875958d981423f` |
| 30 秒性能 trace | 12,671 B | `bb8b987649642f6860799b59ecd457fbb6171cba05c1ff542b6a17ad28a906f0` |
| Lighthouse mobile JSON | — | `802da88dcc667611e61fcb501bbaed11a76179ced91490af11b933bab3e935a8` |
| Lighthouse desktop JSON | — | `3e216a35d8612d9d01c91668dbb1af212914056aaf0a76b7bb29bddea13251c3` |

## 内部设计代理评分

这是项目内部对标代理，不是 Awwwards、FWA 或 CSS Design Awards 的外部评审，
也不代表获奖声明。

| Awwwards proxy | 分数 | 依据 |
| --- | ---: | --- |
| Design | 8.8 | 非对称空间舞台、六组主题模式、统一字体/材质/状态轨迹 |
| Usability | 8.5 | 真实任务流、风险明文、响应式与键盘/reduced-motion 路径 |
| Creativity | 8.7 | 状态驱动单 Canvas 与 kinetic transcript 形成同一叙事 |
| Content | 8.1 | 产品文案克制且层级明确，技术 payload 保真 |
| 加权总分 | 8.62 | Design 40% / Usability 30% / Creativity 20% / Content 10% |

| CSSDA proxy | 分数 |
| --- | ---: |
| UI | 8.8 |
| UX | 8.5 |
| Innovation | 8.7 |
| 平均 | 8.67 |

## 边界与下一阶段

- `/preview/` 仍是并行入口，不切换默认 `/`，不删除旧静态 Workbench。
- 文件、编辑、diff、runs/review、完整 health/settings/tools/resource 面属于 Phase 2。
- 不含 Monaco、桌面壳、远程访问、Marketplace、WebGL/3D 或浏览器 config 写入。
- Node.js 只用于开发与构建；staged preview 的运行时只依赖现有 Python server。
