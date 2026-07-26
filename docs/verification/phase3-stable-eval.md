# Phase 3D Eval 验收记录

- 日期：2026-07-25
- 状态：实施中；尚未通过完成门
- 设计：[`2026-07-25-phase3-stable-eval-design.md`](../superpowers/specs/2026-07-25-phase3-stable-eval-design.md)
- 计划：[`2026-07-25-phase3-stable-eval.md`](../superpowers/plans/2026-07-25-phase3-stable-eval.md)

## 当前边界

3D 只实现 4 个内置 FakeLLM case、真实 `run_once` 指标、稳定判定、CLI 退出码与本地 report。
真实 Provider benchmark、用户 case/plugin、Web 管理面、CI 服务和趋势数据库不在本切片。

Project vNext 核心仍未完成；完成本切片后仍需 Phase 3E–3I 和最终全链路缺陷清零。Phase 4–5
继续是需求触发项。

## 待验证

- [ ] 4 个固定 case 的完成/错误/Tool 次数与副作用期望正确
- [ ] 两次运行的 deterministic signature 一致，duration 不参与门禁
- [ ] workspace config/secrets/MCP/Skills 不污染 Fake gate
- [ ] failure detail/report/CLI 退出码有界、脱敏且可审计
- [ ] link/reparse、非法定义与原子发布失败安全
- [ ] 目标、全量、真实 CLI、wheel 与提交后复验通过
- [ ] D 盘 temp/worktree/process 清理通过
