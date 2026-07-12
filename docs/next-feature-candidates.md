# 下一步功能候选（2026-07-11 交接）

上一功能「Workbench 流式输出与输入区精简」已完成验收（提交 8b5a954→1b49f02）。
本文档供新会话选题使用。做法沿用既有流程：先写 spec（docs/superpowers/specs/）
和 plan（docs/superpowers/plans/），按任务 TDD 实现，pytest 在用户机器统一门禁。

## 交接必读

- 分支:codex/v3.0-frontend-modules,领先 origin 十几个提交,先 push。
- `native_tools = true` 已是日常配置;DeepSeek thinking 模型只支持 `tool_choice: "auto"`。
- 沙箱挂载不可信(曾多次损坏提交):git 提交在用户机器跑,只 stage 任务列出的文件,
  `-c core.autocrlf=input`;校验用 pytest→commit→`git status --short` 为空,
  不要用 PowerShell `git show | Set-Content`(GBK 乱码)。
- 沙箱 Python 3.10 无法 import 本项目(需 3.11+ StrEnum),验证只能 py_compile。
- Workbench 端口:8000–8019 被 Windows winnat 保留,用 `--port 18080`。

## 候选 1:命令白名单扩展（推荐先做）

**动机:** `run_command` 是目前 agent 能力的最大瓶颈。现状(src/agent/tools/shell.py
`_policy_denial`)默认只放行:pytest、rg、只读 git、`python -c`、`python -m pytest`,
其余一律 "Command is not allowed by default"。code-dev 定位的 agent 连
`python script.py`、`pip show`、`npm test` 都跑不了。native FC spec 的范围外清单里
它是唯一带期数的项(「第三期命令白名单」),算排过队。

**思路:**
- 新配置键 `allowed_commands`(list[str],默认 []),用户在 .agent/config.toml 按
  argv 前缀声明放行,如 `["python", "pip show", "npm test"]`,匹配即放行。
- 硬边界不变:SHELL_WRAPPERS / NETWORK_COMMANDS / DANGEROUS_COMMANDS 拒绝清单
  绝对优先,白名单不可越过;路径校验(_validate_path_arguments)与沙箱解析照旧;
  审批策略(risky-confirm)不动——放行只是过策略层,执行前仍走现有审批。
- config.py 加键(参考 native_tools 的五处同模式);doctor/config show 输出;
  Web 设置面板可读(写入白名单是否开放 allowed_commands 需要在 spec 里决策——
  它是 list 且安全敏感,建议第一期不开放 Web 写)。

**风险:** 用户把危险命令写进白名单——靠拒绝清单优先级 + 文档警告 + 审批兜底。
**验收:** 白名单命令可执行、拒绝清单不可越过、默认行为零变化、真实 run 冒烟。

## 候选 2:端点能力自动探测

**动机:** `native_tools` 目前是手动开关;换端点(如 Ollama 本地模型不支持 tools)
时配错会得到 400/ProviderError。自动探测可免配置。

**思路:**
- doctor 或首次调用时发一次带 tools 的最小请求,按响应(200 vs 400 特征错误)
  判定端点是否支持原生工具,缓存判定结果(进程内即可,或写 .agent/ 状态文件)。
- 判定失败自动回落 JSON 协议并在 CLI/Workbench 显示提示;`native_tools` 配置
  保留为显式覆盖(true=强制原生,false=强制 JSON,新增 "auto" 值?spec 里定)。

**风险:** 各端点 400 错误形状不一,判定要保守(不确定就回落 JSON);多一次探测
请求的成本。**用户目前只用 DeepSeek,收益有限——除非近期要接 Ollama,否则往后排。**

## 候选 3:并行多工具调用

**动机:** 原生协议里模型可返回多个 tool_calls,目前只取 index 0,其余丢弃
(_envelope_from_tool_message / _ToolCallAssembler 均只认第一个)。

**思路:** 循环内按序执行多个动作、观察逐个回喂;审批语义要重新设计(一批里
混有需审批动作怎么办)、错误恢复预算按动作还是按轮计,都要 spec 决策。

**风险:** 改动面在 loop.py 核心循环,审批/恢复/迭代预算三条机制都要联动;
`tool_choice: "auto"` 下 DeepSeek 实测极少发并行调用,ROI 低。**建议最后做。**

## Backlog「Do later」(有明确触发条件,未触发不做)

1. Web 端 provider 设置写入 → 前置:配置回滚语义。
2. 打包可执行文件 → 前置:需要分发给非开发者。
3. 桌面壳 → 前置:浏览器 Workbench 不够用。
