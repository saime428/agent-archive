# Orb 状态视觉基线实施计划

- 日期：2026-08-06
- 对应设计：`docs/superpowers/specs/2026-08-06-thinking-orbs-state-baselines-design.md`

## 任务

1. `frontend/e2e/workbench.spec.ts`：新增 `orbStates` 表（9 个状态 × 驱动方式 × 夹取容器），
   复用既有 `emit()` 助手；`breathing` 与 `connecting` 用 `page.route` 延迟撑住瞬态。
2. 同文件新增 9 × 2 = 18 个截图用例，一律先
   `page.emulateMedia({ reducedMotion: "reduce" })`，只夹容器不拍整页，
   命名 `orb-<state>-<mode>.png`。
3. 新增一个非截图断言：9 个状态的 `canvas.toDataURL()` 两两不同——基线若因上游改动
   退化成同一张图，此断言先响。
4. 首轮生成 18 张基线，**逐张过 vision 描述确认**（墨色与背景对比、形状确实不同）再入库。
5. 连跑两轮 e2e 零 diff，证明不 flake。
6. `npm run check` 全绿；`npm run build:preview` 无 Git 漂移；全量 pytest 复跑。
7. 证据写 `docs/verification/thinking-orbs-state-baselines.md`；`CHANGELOG.md` 补条目；
   提交推送，CI 绿。
