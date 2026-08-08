# Orb 状态视觉基线设计

- 日期：2026-08-06
- 状态：用户已批准（补齐前一片留下的两个验收缺口），待实施
- 前置：`2026-08-06-thinking-orbs-phase-indicators-design.md`
- 范围外：orb 动画中间帧的逐帧比对、上游 `src/engine/` 渲染算法审计

## 背景

前一片把 9 个 orb 状态接进产品，但验收留了两个洞：

1. **现有 14 张视觉基线拍不到任何 orb。** 每个截图断言都先等内容可见才拍，待机态早已结束。
   基线"零变化"因此不构成任何 orb 外观证据，`emulateMedia({ reducedMotion: "reduce" })`
   目前不作用于任何一张。
2. **只肉眼验过 1 个状态**（Settings 里的 `searching`，两组深浅），其余 8 个无证据。

## 前置实测（已完成，决定了本设计）

- **冻结帧逐状态可区分**：6 个状态经真实产品路径驱动，`canvas.toDataURL()` 得到 6 个互不相同的值。
- **冻结帧跨运行确定**：两次独立运行，6 个值逐字节一致（长度与尾串全同）。

两条都成立，所以逐状态截图基线可行且不会 flake。若任一不成立，本设计不能采用。

## 轴的收敛：只有 dark/light，没有三主题

`<Orb>` 只把 `resolvedMode` 传给上游，**主题名 a/b/c 传不进组件**，不可能影响 orb 像素。
前一片验收里写的"三主题 × 深浅"对 orb 而言是过度规格。真实轴只有 `dark` / `light`，
即 9 × 2 = 18 张。

## 基线形状

- 截图**只夹 orb 所在的行级容器**，不是整页。基线图小、稳定，且不会被无关 UI 变动误伤。
- 一律先 `page.emulateMedia({ reducedMotion: "reduce" })`，取上游的确定性单帧。
- 命名 `orb-<state>-<mode>.png`，共 18 张。

## 9 个状态的驱动方式

7 个走既有 `emit()` 助手推 SSE 事件；2 个靠 `page.route` 延迟把瞬态撑住：

| 状态 | 驱动 | 夹取容器 |
|---|---|---|
| `solving` | `model_call_start` | `.utterance-label` |
| `weaving` | `model_stream_chunk` kind=`thinking` | `.utterance-label` |
| `composing` | `model_stream_chunk` kind=`content` | `.utterance-label` |
| `searching` | `tool_start` action=`search_files` | `.utterance-label` |
| `shaping` | `tool_start` action=`apply_patch` | `.utterance-label` |
| `working` | `tool_start` action=`run_command` | `.utterance-label` |
| `listening` | `approval_required` | `.utterance-label` |
| `breathing` | 点「从历史重建」，延迟 `/api/chats/*` 把 `recovering` 撑住 | `.utterance-label` |
| `connecting` | 延迟 `/api/health`，`StatusMark` 停在 `health === null` | `.command-status` |

## 验收

- 18 张基线首轮生成后**逐张人工确认**（含 vision 描述取证）再入库，不得直接 `--update-snapshots` 了事。
- 同一套基线连跑两轮零 diff，证明不 flake。
- 9 个状态两两不同：沿用前置实测的 `toDataURL` 比对，扩到全部 9 个。
- `npm run check` 全绿；全量 pytest 不回归。
- 证据落 `docs/verification/thinking-orbs-state-baselines.md`。
