# 设计:错误恢复循环 + 退役 direct helpers(第一期)

日期:2026-07-09
状态:已获用户批准
范围:`src/agent/core/loop.py`、`src/agent/core/actions.py`、`src/agent/config.py` 及对应测试

## 背景与动机

当前 run loop 对工具错误的处理是"一票终止":

- `loop.py` 中 `terminal = action.action.name in {"done", "ask_user"} or observation.status == "error"`,任何工具错误直接结束整个 run。
- `_should_append_observation_feedback` 仅在 `observation.status == "ok"` 且动作属于低风险集合时回喂观察,错误观察从不回喂,模型没有自我纠正的机会。
- 对比之下,JSON 解析错误已有完整的"错误 → 回喂 → 重试 → 预算耗尽终止"机制(`_build_repair_message` + `repair_attempts`)。本设计将同一模式推广到工具执行层。

另有两个中文关键词短路函数 `_direct_chat_answer` 与 `_direct_external_list_path`(含辅助函数 `_list_dir_final`)内联在 `run_once` 中,绕过模型、技能过滤与工具协议,存在静默误路由风险(如"帮我看看 src/main.py 为什么报错"被拦截为 list_dir),且仅覆盖中文输入。系统提示中已有 "For simple chat, identity, model, or capability questions, return a natural direct answer" 指导,短路函数属冗余,本期整体删除。

## 设计

### 1. 错误可恢复性分类

在 `actions.py` 的 `ErrorCode` 旁定义:

```python
RECOVERABLE_ERROR_CODES: frozenset[ErrorCode] = frozenset({
    ErrorCode.TOOL_FAILED,
    ErrorCode.TIMEOUT,
    ErrorCode.SANDBOX_VIOLATION,
    ErrorCode.INVALID_ARGUMENT,
    ErrorCode.POLICY_DENIED,
})
```

判定标准:模型换个做法(换路径、换工具、缩小范围)就可能绕开的错误为可恢复。

不可恢复(维持立即终止):

- `APPROVAL_DENIED` — 用户明确拒绝;
- `APPROVAL_REQUIRED` — 无审批通道的非交互环境;
- `INTERNAL_ERROR` — hook 阻断等内部故障。

解析类错误(`INVALID_JSON`、`UNSUPPORTED_PROTOCOL_VERSION`、`MISSING_REQUIRED_FIELD`、`UNKNOWN_TOOL` 的解析路径)继续由现有 repair 通道处理,本期不动。

### 2. 终止条件与连续错误预算

`loop.py` 中 terminal 判定改为:

- 动作为 `done` / `ask_user`;或
- 错误观察且错误码不可恢复;或
- 连续错误计数达到预算上限。

连续错误计数器:错误观察 +1,成功观察清零。

预算配置:`AgentConfig` 新增字段 `max_consecutive_errors: int = 3`,并纳入 `_trace_config` 输出。

预算耗尽终止时,最后的错误观察 `details` 中注明 `consecutive_errors_exhausted: true` 及计数值,保证日志与 UI 可解释终止原因。

### 3. 统一观察反馈

`_should_append_observation_feedback` 语义改为:一切非终止观察均回喂。带来两个行为变化:

1. 可恢复错误观察回喂,模型获得纠错机会;
2. `write_file`、`apply_patch`、`run_command` 等动作的成功结果也回喂(现状是写操作后模型"盲飞")。

`_build_observation_feedback_message` 按观察状态分支:

- 成功:维持现有格式;
- 错误:附错误码、错误摘要、details 节选(经既有 budget 截断),并追加指令:"调整方式重试或改用其他工具;不要用相同参数重复同一动作;卡住时用 ask_user 求助。"

两种状态均保留 "UNTRUSTED TOOL OBSERVATION" 框架文案与截断预算。

### 4. 迭代预算提醒

剩余迭代数等于 2 时,向消息列表注入一条提醒:迭代预算即将用尽,已完成则返回 done,未完成则用 ask_user 说明当前进度与剩余工作。每个 run 至多注入一次。各模式迭代上限数值(`_mode_max_iterations`)本期不改。

### 5. 退役 direct helpers

整体删除:

- `_direct_chat_answer`
- `_direct_external_list_path`
- `_list_dir_final`
- `run_once` 开头对应的两段内联分支

删除后所有输入统一走模型路径。相关测试分支同步删除。`PROJECT_CONTEXT.md` 中关于两个 direct helpers 的说明同步更新。

若未来接入的弱模型确实无法处理寒暄类输入,再按需引入显式 pre-router 模块(trigger-based,本期不预留)。

### 6. 测试与验收

新增/调整测试(FakeLLM 脚本化序列):

- 可恢复错误 → 反馈消息追加 → 模型继续执行并可完成任务;
- 连续 3 次错误 → 终止,`consecutive_errors_exhausted` 可见;
- 错误后成功 → 计数器清零,后续错误重新计数;
- `APPROVAL_DENIED` → 仍立即终止;
- 写操作成功结果回喂;
- 剩余 2 次迭代 → 提醒注入且仅一次;
- 寒暄输入与外部路径列目录任务走模型路径(原短路测试改写)。

验收标准:

- `python -m pytest -q` 全绿;
- `python -m agent.cli doctor` 正常;
- 人工冒烟:故意让模型读不存在的文件,确认其收到错误反馈后自我纠正,run 不因单次错误失败。

## 范围外

provider 层、`shell.py` 命令策略(含 `python -c` 现状)、Web 服务器与前端、迭代上限数值、repair 通道机制。

## 后续

第二期:OpenAI 兼容 provider 泛化 → 原生 function calling(fallback 保留现有 JSON 协议)。
第三期:项目级 `allowed_commands` 可配置 + 白名单外命令走审批。
