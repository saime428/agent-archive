# Orb 状态验证证据

- 日期：2026-08-06
- 对应设计：`docs/superpowers/specs/2026-08-06-thinking-orbs-state-baselines-design.md`
- 结论：9 个状态全部有自动化证据，但**不是**设计里预想的像素基线形式。原因见下。

## 设计变更：像素基线不可行，改为位图断言

spec 原计划落 9 × 2 = 18 张截图基线。实际做出来后逐张核对，**发现基线是假的**，两轮排查：

**第一轮：容器截图拍不到 canvas。** 18 张里每种模式只有 6 个唯一哈希，碰撞组恰好是
`searching`/`shaping`/`working`（标签同为 `AGENT / TOOL`）与 `composing`/`weaving`
（同为 `AGENT / STREAM`）。6 个唯一值等于 6 种标签文字——截图内容里根本没有 orb。
这种基线在 orb 完全不渲染时同样会通过。

**第二轮：改夹 canvas 元素后仍有 5 张是空的。** 唯一哈希升到 7；剩余碰撞的文件都是
113–114 字节（空 PNG），而正常的是 271–391 字节。此时 `getImageData` 明确报告
canvas 上有 >20 个非透明像素，同一元素的 `screenshot()` 却返回空图，且只对
`solving`/`weaving`/`composing`/`listening`/`breathing` 这 5 个状态如此。
加 `expect.poll` 重新解析元素、等待真实着色后重跑，结果逐字节不变。

**结论**：Playwright 对这个 20px canvas 的合成不可靠，无法作为证据来源。canvas 位图本身
（`toDataURL`）稳定且可复现，改用它。18 张基线已全部删除，未入库。

## 现行断言

`frontend/e2e/workbench.spec.ts` 中 `renders a distinct orb per state in <mode> mode`，
dark / light 各一个：

- 9 个状态各开**独立 browser context**。共用 page 会让 mock 后端的 job 状态跨导航残留，
  上一回合会把下一回合的输入框禁用——这是 spec 阶段一次循环测试失败的真因。
- 一律 `emulateMedia({ reducedMotion: "reduce" })`，取上游确定性单帧。
- 每个状态断言 canvas 着色像素 > 20（非空），再取 `toDataURL`。
- 最后断言 9 个位图**两两不同**：把两个 phase 指向同一动画的映射回归会让这个集合塌缩。

## 9 个状态的驱动方式

| 状态 | 驱动 | 容器 |
|---|---|---|
| `solving` | `model_call_start` | `.live-turn .agent-utterance .utterance-label` |
| `weaving` | `model_stream_chunk` kind=`thinking` | 同上 |
| `composing` | `model_stream_chunk` kind=`content` | 同上 |
| `searching` | `tool_start` action=`search_files` | 同上 |
| `shaping` | `tool_start` action=`apply_patch` | 同上 |
| `working` | `tool_start` action=`run_command` | 同上 |
| `listening` | `approval_required` | 同上 |
| `breathing` | `error` 事件 + 点「从历史重建」，延迟 `/api/chats/*` | 同上 |
| `connecting` | 延迟 `/api/terminal*`，停在 Terminal 读取态 | `.terminal-view p.overview-note[role="status"]` |

两个驱动细节值得记：

- `breathing` 必须用 `error` 而非 `failed`。`failed` 在 `TERMINAL_EVENTS` 里，会触发
  `settleJob()` 把 `live` 重置为 `initialChatState`，「从历史重建」按钮还没渲染就没了。
- `connecting` 的 `/api/terminal*` 延迟**不能加 `times: 1`**。该视图挂载时轮询两次，
  只拦第一次的话第二次会立刻清掉 loading。

## 结果

- `renders a distinct orb per state`：dark / light 各 9 个状态，9 个唯一位图，两轮稳定。
- 全量 e2e 61 passed / 1 skipped（skipped 为需 `PERF_EVIDENCE` 的性能取证用例）。
- `npm run typecheck` / `lint` / `check:ui` / `test:run`（38）全绿。
- `npm run build:preview` 后 `src/agent/web/static/preview` 无变更——本切片只动测试。

## 仍未覆盖

- **没有任何 orb 外观的人工确认扩展到全部 9 个状态。** 前一片用 vision 确认过
  `searching` 在深浅两种背景下的墨色对比；其余 8 个只有"非空且互不相同"的机器断言，
  没有"看起来对不对"的判断。
- 上游 `src/engine/` 9 个渲染文件仍未审计。
