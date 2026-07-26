# 设计：Phase 3E 编辑器与工作区搜索

- 日期：2026-07-25
- 状态：已实施并通过独立验收
- 上位方向：[Phase 3 方向分析与审查](../../project-vnext-phase3-direction-review.md)

## 目标

把现有 React Files 视图从单文件 textarea 升级为可完成真实小型编码任务的工作区：桌面端使用
Monaco 多标签打开、编辑、保存和关闭，递归搜索工作区文本或路径并跳到匹配行。所有写入继续只走
现有 `/api/file/save`、approval 与 snapshot 链，搜索只读且受 workspace sandbox 约束。

本切片完成后只允许声明“3E Editor/Search 完成”；Phase 3 和 Project vNext 核心仍需 3F-3I 与最终
全量缺陷清零。

## 编辑器与标签模型

- 精确锁定 `monaco-editor@0.56.0`，直接使用官方 ESM API 和 Vite Worker；不增加 React 包装层、
  状态库、LSP、extension host 或语言服务器。
- Monaco 只在桌面 Files 视图实际打开文件后懒加载。官方明确不支持移动浏览器，因此小于 768px
  使用原生 textarea fallback；两条渲染路径共享同一 tab/buffer/save 状态，不建立第二套业务逻辑。
- 单个 Monaco editor 在标签间切换 model；每个文件保留独立 buffer、baseline、dirty、只读状态和
  光标/滚动视图。组件卸载时释放 editor、model、listener 与 Worker 引用。
- 最多同时打开 20 个标签。文件仍受既有 20,000 字符读取预算约束；截断、二进制或包含 UTF-8
  replacement character 的文件只读。
- 单击文件或搜索结果打开/激活标签；搜索文本命中同时跳到对应行。关闭 dirty 标签、切换离开 Files、
  关闭工作台或浏览器刷新都必须有保护；关闭 clean 标签不弹确认。
- `Ctrl/Cmd+S` 与保存按钮都只打开现有显式保存确认；成功后更新该标签 baseline 和 run id。失败保留
  buffer 与 dirty 状态。标签切换和目录浏览不丢弃其他 buffer。

## 搜索 Interface

新增独立只读 Interface：

```text
GET /api/search?query=<UTF-8 text or glob>
```

`query` 必填、trim 后非空、最大 200 字符。普通 query 对相对路径与 UTF-8 文本做不区分大小写的
递归搜索；包含 `*?[]` 时沿用现有 `search_files` 的 glob 路径语义。响应固定为：

```json
{
  "query": "needle",
  "path": ".",
  "matches": [{"path": "src/app.py", "kind": "text", "line": 12, "excerpt": "..."}],
  "total_matches": 1,
  "truncated": false,
  "scan_truncated": false,
  "scanned_files": 20,
  "skipped_files": 2
}
```

后端通过现有 `search_files` executor 复用 sandbox、glob、binary detection、excerpt 和错误语义，不复制
搜索算法。为让 Agent Tool 与 Workbench 都可用，共享遍历改为确定性的 `os.walk` 并在进入目录前剪枝：
`.git`、`.venv`、`node_modules`、`dist`、`build`、`__pycache__`、`.pytest_cache` 及受保护的
`.agent/runs` 不扫描。单文件正文最多读取 1 MiB、单次最多扫描 10,000 个文件、返回 50 个匹配、
excerpt 200 字符；超限文件仍可产生路径命中，但不读正文。若扫描达到上限，`scan_truncated=true`，
此时 `total_matches` 只表示已扫描范围内发现的数量，UI 使用“至少”表述。

搜索固定在当前 workspace，不读取 `computer_read_enabled`，不接受绝对路径或 parent escape。请求错误
返回既有有界 JSON 400；未知、二进制、权限或竞态文件按“跳过并计数”处理，不能让整次搜索 500。

## 依赖与包体门

- npm registry 元数据：`monaco-editor@0.56.0` 展开 97,911,464 bytes、1,909 files；这是开发安装
  成本，不等于发布包体。
- Monaco 必须单独异步 chunk，现有首屏同步 JS gzip 增量不超过 50 KiB。
- 构建后的 Monaco JS/CSS/font/Worker 原始增量上限 15 MiB、gzip 总量上限 5 MiB；verification 记录
  实际值和 wheel 增量。超限即停止，不用提高阈值掩盖回归。
- 只注册本项目常见语言的轻量语法贡献；不加载 TypeScript/JSON language worker、智能补全或 telemetry。

## 状态、失败与可访问性

- 搜索有 idle/loading/empty/error/truncated 状态；重复提交时只接受最后一次请求结果，防止慢响应覆盖。
- 标签、关闭和搜索结果均为可聚焦 button；active/dirty/read-only 有文本或 ARIA 语义，不只依赖颜色。
- Monaco 设置 `ariaLabel`，原生 fallback 使用同一 label；保存确认后焦点回到编辑器或触发按钮。
- 搜索结果显示 path、line 与有界 excerpt；payload 使用现有 `data-payload` 截断策略，长路径不撑宽布局。
- 主题沿用现有 resolved light/dark mode，不新增视觉系统或动画。

## 验收

- 打开至少三个文件、分别编辑、切换后 buffer 与视图仍在；clean/dirty 标签关闭语义正确，工作台离开
  与 beforeunload 保护生效。
- 保存仍产生真实 run/snapshot；失败不清 dirty；truncated/replacement/binary 保持只读。
- 普通文本、路径、glob、Unicode、无结果、截断、超大文件、忽略目录、权限竞态和 sandbox escape 有测试。
- 搜索结果点击打开正确标签并跳到行；相同结果可重复跳转；窄屏 textarea、键盘保存和 focus 可用。
- Python 定向/全量、frontend unit/lint/typecheck/build/Playwright、真实 served Workbench、wheel 与 detached
  worktree 通过；记录包体、Worker、snapshot 和 sandbox 证据。

## 非目标

- 文件创建、重命名、删除、批量替换、正则搜索、索引服务、watcher、ripgrep 进程或搜索历史。
- LSP、智能补全、diagnostics、format-on-save、协作编辑、split editor、固定/恢复标签或 reload 后 buffer 恢复。
- Git/Diff、Terminal、Command/Layout、legacy retirement 或 Phase 4-5 需求触发项。
