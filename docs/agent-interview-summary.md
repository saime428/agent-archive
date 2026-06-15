# Agent 项目面试讲述总结

## 1. 项目一句话介绍

这个项目是一个从零实现的 Python CLI Agent Core，目标是为本地代码开发场景提供一个安全、可审计、可扩展的命令行智能体框架。它不是简单地把大模型接到 shell 上，而是把模型输出约束为内部结构化动作协议，再由核心层统一做解析、权限校验、沙箱约束、工具执行、日志记录和结果反馈。

面试时可以这样开场：

> 我做的是一个本地代码开发 Agent 的最小核心框架。它支持命令行运行任务、读取项目上下文、调用受控工具、接入 DeepSeek Provider，并且重点解决了 Agent 落地中比较关键的安全边界、可观测性、可恢复性和扩展能力问题。

## 2. 为什么做这个项目

现在很多 coding agent 的核心难点并不只是“能不能让模型生成代码”，而是模型和本地环境之间缺少可靠边界：模型可能输出非法 JSON、调用危险命令、读取或写入越界路径、把文档里的恶意提示词当成指令、或者在失败后留下不可追踪的状态。

所以这个项目的设计重点是：

- 让模型只输出受控的 JSON action，而不是直接执行命令。
- 所有文件、shell、git、文档工具都经过统一的策略层判断。
- 默认只允许 workspace 内操作，保护 `.agent/runs`、`.git`、`__pycache__` 等内部状态。
- 对写文件、patch、运行命令等高风险动作做 approval fail-fast。
- 所有运行都落盘成 durable logs，并且在写日志前做敏感信息脱敏。
- 文件写入前创建 snapshot，方便恢复。
- 后续能力如 Provider、Skills、Memory、Hooks、Documents 都围绕这个安全核心逐步扩展。

这个项目可以体现我对 Agent 工程化的理解：模型只是决策来源之一，真正可靠的 Agent 需要协议、策略、工具边界和审计闭环。

## 3. 当前项目进展概览

项目目前已经推进到 v0.4 阶段。整体不是一次性堆功能，而是按可验收版本逐步演进。

| 版本 | 主题 | 当前状态 |
| --- | --- | --- |
| v0.1 | Core MVP | 已完成并有验收清单 |
| v0.2 | Provider、Skills、Memory、Hooks | 已完成并有验收清单 |
| v0.3 | 本地文档读取与 Markdown 报告 | 已完成并有验收清单 |
| v0.4 | DeepSeek Provider smoke、真实运行可观测性 | 已完成主要 slice，并记录 deferred 项 |

截至当前，测试集中已经收集到 261 个测试用例，覆盖 action 协议、CLI、配置、安全策略、沙箱、工具层、run loop、DeepSeek、文档工具、记忆、技能、hooks、日志和脱敏等模块。

## 4. 技术栈与项目结构

项目使用 Python 3.11+，核心依赖包括：

- `typer`：构建命令行接口。
- `rich`：优化 CLI 输出。
- `pydantic`：做结构化数据和 schema 校验。
- `pypdf`：支持 PDF 文档读取。
- 可选文档依赖包括 `python-docx`、`openpyxl`、`python-pptx`，用于 Word、Excel、PowerPoint 读取。
- `pytest`：自动化测试。

主要目录结构如下：

```text
src/agent/
  cli.py                    # CLI 入口和命令注册
  config.py                 # 配置加载、合并和安全约束
  core/
    actions.py              # action / observation 协议解析和校验
    loop.py                 # agent 主运行循环
    budget.py               # 上下文和输出预算控制
    run_store.py            # durable run 读取与展示
    redaction.py            # 敏感信息脱敏
    project_instructions.py # AGENTS.md 加载
    skills.py               # skill 发现与加载
    memory.py               # memory candidate、accept、undo
    hooks.py                # 生命周期 hooks
  llm/
    base.py                 # LLMClient 抽象
    fake.py                 # Fake provider，用于离线测试
    deepseek.py             # DeepSeek provider 和 smoke 测试
  policy/
    approvals.py            # approval 策略
    sandbox.py              # workspace 沙箱路径检查
  tools/
    filesystem.py           # 文件读写、搜索、patch
    shell.py                # 结构化命令执行
    git.py                  # git status / diff
    documents.py            # PDF / Office 读取与 Markdown 报告
```

测试目录 `tests/` 与模块基本一一对应，覆盖面比较细，能说明项目不是演示型脚本，而是按可维护组件来搭的。

## 5. 核心设计：模型不能直接控制环境

这个项目最重要的设计是内部 action protocol。模型不能直接执行 shell，也不能直接读写文件，只能返回类似这样的结构化 JSON：

```json
{
  "message": "I need to inspect the project structure first.",
  "action": {
    "name": "search_files",
    "args": {
      "query": "*.py"
    }
  }
}
```

核心层拿到模型输出后，会做几件事：

1. 解析 JSON，校验 action 名称和参数 schema。
2. 忽略模型自己伪造的 `run_id`、`action_id`、时间戳等元数据。
3. 由 core 注入可信的 protocol metadata。
4. 进入 policy 层判断这个 action 是否允许、是否需要 approval、是否必须拒绝。
5. 通过 tool executor 执行工具。
6. 将工具结果包装为 observation，再反馈给模型或结束运行。
7. 写入 `.agent/runs/<run-id>/` 目录，形成可审计记录。

这样做的好处是：即使模型输出不稳定，系统仍然有确定的边界；即使模型尝试越权，也只会得到标准错误 observation，而不会直接影响本地环境。

## 6. v0.1：安全核心 MVP

v0.1 的目标是先把 Agent 最小闭环跑通，同时把安全边界做扎实。

已完成的能力包括：

- `agent run "<task>"` 可以通过 FakeLLM 执行一个完整 action loop。
- 支持 `agent doctor`、`agent runs list`、`agent runs show <run-id>`。
- 支持 `agent tools list`、`agent config show`、`agent config doctor`。
- 加载项目中的 `AGENTS.md` 作为只读上下文。
- 实现配置合并：defaults、global config、project config、CLI override。
- 防止项目配置静默降低安全级别，比如不能偷偷设置 `danger-full-access` 或 `approval=never`。
- 实现 action / observation 的版本化协议。
- 文件工具支持 `read_file`、`write_file`、`apply_patch`、`search_files`、`list_dir`。
- shell 工具只接受结构化 argv，不接受 `powershell -Command`、`cmd /c`、`bash -lc` 这类 shell wrapper。
- git 工具支持 `git_status` 和 `git_diff`。
- 写文件前创建 snapshot，run summary 中给出 restore guidance。
- durable logs 写入前做 redaction，避免泄漏 token、API key 等敏感信息。
- `--dry-run` 能验证计划但跳过写文件和 shell 命令副作用。

这个阶段的重点不是功能多，而是把“模型提出动作，系统验证并执行”的主链路打牢。

## 7. v0.2：Provider、Skills、Memory、Hooks

v0.2 在核心稳定后增加扩展能力。

Provider 方面：

- 增加 DeepSeek 配置字段：`provider`、`model`、`deepseek_api_key_env`。
- `agent run --provider fake|deepseek --model <model>` 可以选择模型提供方。
- DeepSeek client 使用 OpenAI-compatible chat completion 协议。
- provider/model 信息写入 run summary 和 trace config。
- doctor 只检查 API key 是否存在，不在诊断阶段发起网络请求。

Skills 方面：

- 支持 `agent skills list` 和 `agent skills show <name>`。
- 支持内置 skills 和项目 skills。
- 使用 progressive disclosure：发现阶段只读 metadata，选中后才加载完整 `SKILL.md`。
- skill 内容会被标记为不可信上下文，不能绕过 policy、approval 或 sandbox。

Memory 方面：

- run 结束时可以生成 memory candidates，但默认不会自动接受。
- 支持 `agent memory review/list/accept/undo`。
- memory entry 记录 source、timestamp、status。
- undo 通过 tombstone 实现，不是静默删除历史。
- memory retrieval 是确定性的，并受预算限制。

Hooks 方面：

- hooks 默认关闭。
- 显式开启后可以记录生命周期审计日志。
- 非阻塞 hook 失败只记录，不打断主流程。
- 阻塞 hook 失败会返回标准错误 observation。

这一版体现的是扩展性：Provider、技能、记忆、hooks 都能接入核心循环，但都不能破坏安全模型。

## 8. v0.3：本地文档研究能力

v0.3 加入文档工具，定位是让 Agent 能读取本地 PDF 和 Office 文档，并生成有来源标注的 Markdown 报告。

已完成能力：

- `read_pdf`：通过 `pypdf` 提取 PDF 文本。
- `read_docx`：提取 Word 段落文本。
- `read_xlsx`：提取 Excel sheet、表头、shape 和示例行。
- `read_pptx`：提取 PowerPoint slide title 和文本。
- `write_markdown_report`：生成带 source-grounding notice 和 Sources section 的 Markdown 报告。
- 所有文档读取都经过 workspace sandbox。
- 文档内容进入 observation 前会被预算截断。
- 文档内容被包装为 `UNTRUSTED DOCUMENT SOURCE MATERIAL`。
- 写报告属于确认型动作，会在非交互场景 fail fast，dry-run 会跳过实际写入。

这里我特别处理了文档 prompt injection 风险：文档里的内容只作为 source material，而不能变成系统指令。比如 PDF 里出现“忽略之前所有指令”，系统也只会把它当作文档正文，不会改变 tool policy 或当前用户任务。

## 9. v0.4：真实 Provider Smoke 与可观测性

v0.4 的重点是把真实 Provider 连接做得显式、可诊断，同时不破坏默认离线测试。

已完成能力包括：

- `agent provider smoke deepseek --model <model>`。
- smoke 命令使用配置的 API key env 和模型。
- smoke 只做一次非流式 chat completion 请求，不创建 `.agent/runs` 记录，也不执行工具。
- smoke 会验证模型返回的是合法 `done` action。
- 缺少 DeepSeek API key 时，在发起网络请求前快速失败。
- 默认 provider 仍然是 `fake`，所以本地测试不依赖真实网络或密钥。
- 真实 provider run 会收到内部 action protocol 指导。
- 低风险工具 observation 会反馈给模型，并标记为不可信运行时数据。
- run summary 暴露 `completed`、`terminal_reason` 和失败时的 `failure_explanation`。

这一版主要解决“怎么判断真实模型能否按协议工作”和“失败后怎么让操作者看懂”的问题。

## 10. 安全与可靠性亮点

这个项目在面试中比较值得讲的亮点有以下几个。

第一，结构化 action protocol。模型输出必须经过 schema 校验，未知工具、非法参数、额外字段、无效 JSON 都不会直接执行，而是进入 repair loop 或返回标准错误。

第二，核心生成可信元数据。`run_id`、`action_id`、`observation_id` 和时间戳由 core 生成，不信任模型伪造的元数据，避免日志关联和审计被污染。

第三，workspace sandbox。路径检查不是简单字符串前缀判断，而是解析真实路径，拒绝父目录逃逸、symlink/junction 逃逸，并保护 `.agent/runs`、`.git`、`__pycache__`。

第四，shell 执行受控。`run_command` 只接受 argv 列表，拒绝 shell wrapper、网络命令、越界 cwd 和指向受保护路径的参数。

第五，写入前 snapshot。`write_file` 和 `apply_patch` 在修改前记录原始状态，新文件也记录“之前不存在”，方便 run 结束后恢复。

第六，日志脱敏。run logs、tool calls、summary 等 durable 输出都会经过 secret-like value redaction，避免把 API key、token、authorization header 等写进持久日志。

第七，文档隔离。PDF/Office 内容被明确标注为不可信 source material，不能覆盖 system/user/policy 指令。

## 11. 可演示的命令路径

如果面试中要现场演示，可以按从安全到能力的顺序来：

```powershell
python -m agent.cli doctor
python -m agent.cli config show --cwd F:\agent
python -m agent.cli tools list
python -m agent.cli run --provider fake --cwd F:\agent "inspect project"
python -m agent.cli runs list
python -m agent.cli runs show <run-id>
python -m agent.cli skills list --cwd F:\agent
python -m agent.cli memory review --cwd F:\agent
python -m agent.cli provider smoke deepseek --model deepseek-v4-flash
```

如果没有 DeepSeek API key，可以强调 smoke 会在缺 key 时 fail fast，不会进行网络访问；这本身也是 provider diagnostic 的设计目标。

## 12. 测试与验收情况

项目目前有 261 个 pytest 测试被收集，覆盖范围包括：

- action parser 和 observation schema。
- approval 策略。
- context budget 截断。
- CLI 命令。
- config merge 和安全降级防护。
- DeepSeek client 和 provider smoke。
- README 与版本验收文档。
- PDF / Office document tools。
- FakeLLM。
- hooks。
- agent run loop。
- memory。
- AGENTS.md 项目指令加载。
- redaction。
- run store。
- sandbox。
- skills。
- filesystem、git、shell tools。

项目还维护了 `docs/v0.1-acceptance.md` 到 `docs/v0.4-acceptance.md`，每个版本都有 Implemented / Tested 和 Deferred 项，便于解释项目是如何分阶段交付的。

## 13. 我在项目中的工程取舍

这个项目里有几个比较明确的取舍：

- 先做安全核心，再做大模型能力。v0.1 只用 FakeLLM，是为了让协议、沙箱、日志、工具执行先稳定。
- 默认离线可测。DeepSeek 是可选 provider，默认 provider 仍是 fake，因此 CI 和本地测试不依赖真实 API key。
- 不追求一开始就全自动。memory 默认 candidate review，hooks 默认关闭，写操作默认需要确认或 fail fast。
- 文档工具先做读取和 Markdown 报告，不做复杂 Office 编辑、OCR 或 PowerPoint 布局生成，避免 v0.3 范围失控。
- 使用 deterministic matching 和预算控制，而不是过早引入 embedding 或复杂 planner。

这些取舍让项目更容易验证，也更贴近真实工程落地：先把边界、审计和失败路径做正确，再逐步扩展能力。

## 14. 可以给面试官的讲述主线

建议面试时按这条线讲：

1. 我想解决的是本地 coding agent 的安全可控执行问题。
2. 所以我没有让模型直接操作文件或 shell，而是设计了内部 action / observation 协议。
3. 核心 run loop 负责解析、校验、授权、执行、记录和反馈。
4. v0.1 先完成安全核心，包括沙箱、approval、snapshot、redaction、dry-run、durable logs。
5. v0.2 再接入 Provider、Skills、Memory、Hooks，但都不能绕过核心 policy。
6. v0.3 增加本地文档读取，同时把文档内容当成不可信 source material，防 prompt injection。
7. v0.4 增加 DeepSeek smoke 和真实运行可观测性，确保真实 provider 能按协议工作。
8. 最后用 261 个测试和版本验收文档说明项目是可验证、可迭代的工程，而不是一次性 demo。

## 15. 后续规划

当前 deferred 的方向主要包括：

- Provider streaming response。
- Provider retry/backoff policy。
- 原生 provider tool-call schema 适配。
- 更复杂的 planner。
- 更深入的文档 prompt-injection fixture。
- `write_docx_report`。
- shell-command hooks 的独立 sandbox 和 approval policy。
- embedding-backed memory retrieval。
- 更完整的真实 provider 集成测试，但仍保持默认测试不依赖网络。

这些后续规划可以自然接在当前架构上，因为项目已经有稳定的 action protocol、policy 层、tool 层和 run logging 机制。

## 16. 面试总结版

一句话总结：

> 这是一个面向本地代码开发场景的 Python CLI Agent Core。我重点实现了结构化 action 协议、workspace sandbox、approval fail-fast、可恢复 snapshot、日志脱敏、durable run store、DeepSeek provider、skills、memory、hooks 和本地文档读取。项目目前推进到 v0.4，有 261 个测试和四个版本验收文档支撑，核心价值是把大模型从“不受控文本生成器”变成一个在明确边界内调用工具的可审计执行系统。

