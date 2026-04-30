---
name: jira-analyze
description: 对 Jira Issue 进行深度根因分析并给出修复建议。当用户要求分析某个 Jira issue 时使用此 skill，支持自动下载 Jira 附件、分析日志、定位可疑代码、输出根因诊断与修复建议。采用结构化沉淀和 case-based reasoning 实现可持续学习。
---

# Jira Issue 深度分析 (v2)

## 触发条件

当用户要求以下操作时使用此 skill：
- "分析 Jira issue XXX"
- "帮我看看这个 Jira 问题"
- "对 ISSUE-123 进行根因分析"
- "调查这个 bug"

## Todo List（分析检查清单）

```
□ 调用 enter_analyze(issue_key) 获取 Jira 信息
□ 【重要】根据jira的基本信息，从confluence查询相关文档和分析经验
□ 分析日志（grep_files 过滤关键词，参考文档中的关键词）
□ 【重要】根据jira和log的信息，从opengrok查找相关的代码
□ upsert_artifact 记录从confluence获取的页面ID和模块知识（confluence_notes）
□ upsert_artifact 记录日志发现（log_findings）
□ upsert_artifact 记录相关代码发现（code_findings）
□ upsert_artifact 记录分析过程（analysis_process）
□ grep/read 本地 history_path，检索历史案例，如果有相似案例，通过jira工具查询
□ 整理最终结论（结论、根因、证据、修复建议、历史案例参考）
□ 调用 exit_analyze(issue_key, conclusion) 完成分析
```

## 关键约束（违反会导致分析失败）

```
1. 必须按照todo来执行分析过程
2. 所有产物必须通过 upsert_artifact 或 exit_analyze 写入
3. exit_analyze 是唯一结束分析的方式
4. 最终传给 exit_analyze 的必须是简短结论段落，不是 JSON 草稿，也不是长篇调试转录
```

## 当前存储模型

- 分析过程笔记持久化到 Confluence，不再写本地 `.jira-analysis` artifacts/history。
- 每个 Jira issue 的 artifact 会落到一个独立子页面：`MMAD - Memory - Artifact - {ISSUE_KEY}`。
- 如果该 issue 的 artifact 页不存在，第一次 `upsert_artifact` 会自动创建。
- `upsert_artifact(issue_key, title, content)` 以 `title` 为主键覆盖内容；同名 title 再写会替换，不会追加重复条目。
- `exit_analyze(issue_key, conclusion)` 不保存完整 conclusion，只会从 `conclusion` 推导并写入 history 的 `summary` 和 `tags`。
- 本地会保留当前分析周期的临时附件目录，以及 `history_path` / `artifacts_path` 原始缓存文件；`exit_analyze` 后会一起清理。

## 步骤详解

### Step 1: enter_analyze

先调用 `enter_analyze(issue_key)`，拿到分析工作区和上下文。

重点阅读以下字段：
- `summary`: Jira 基本信息摘要，包含标题、状态、优先级、组件、标签
- `description`: Jira 描述正文
- `comments`: 评论区内容，常有补充现象、复现步骤、临时结论
- `attachments`: 附件下载结果
- `history_path`: 本地 history 原始缓存文件路径；内容来自 Confluence `body.storage`，需要你自己用 `grep_files` / `read_file` 检索
- `artifacts_path`: 本地 artifact 原始缓存文件路径；内容来自 Confluence `body.storage`

执行要求：
- 先快速判断 issue 对应的模块、现象、时间线、是否有日志附件
- 先对本地 `artifacts_path` 做 grep/read，再优先读取 `confluence_notes`、`log_findings`、`code_findings`、`analysis_process` 这几类已有标题
- 如果要参考历史案例，必须显式对 `history_path` 做 grep/read，不要假设系统已经帮你筛好
- 如果附件下载失败或没有日志，在 `analysis_process` 中明确记录信息缺口

### Step 2: 查 Confluence 模块文档【重要】

**必须在分析日志之前完成！**

在 "MMAD+-+Docs" 页面（ID: 665519915）下：
1. 获取子页面列表
2. 根据 Issue 的组件（components）匹配模块名
3. 读取匹配模块的文档内容
4. 提取：调试步骤、错误码含义、常见原因、关键词

执行要求：
- 先按 Jira `components`、标题关键词、日志中的模块名匹配页面
- 如果没有精确匹配，退而求其次找相邻模块、公共调试指南、历史分析经验
- 至少记录：页面 ID、页面标题、为什么认为它相关
- 不要把整页文档照抄进笔记，只保留后续分析要用的知识点

### Step 3: 记录 Confluence 知识【重要】

用 `upsert_artifact(issue_key, title="confluence_notes", content=...)` 记录：
- 模块关键调试步骤
- 错误码及含义
- 常见原因和解决方案
- 用于 grep 的关键词列表
- 参考页面 ID / 标题

建议结构：
- 模块判断
- 参考页面
- 调试关键词
- 常见根因
- 本次 issue 值得重点验证的方向

### Step 4: 分析日志【重要】

优先分析 `attachments` 中 `type=log` 且 `status=downloaded` 的文件。带着文档关键词去筛日志，不要盲读全部附件。

先做两轮检索：
1. 用 Confluence 提取的模块关键词、错误码、关键函数名筛选
2. 用通用故障词补充筛选：`error` / `fail` / `timeout` / `panic` / `exception` / `warning`

建议方式：
```
grep_files(pattern="文档关键词|通用错误词", ...)
```

- 小文件 (< 200KB)：直接读取全文
- 大文件：优先用文档关键词过滤
- 结合文档知识解读错误含义
- 关注时间顺序：先出现的异常通常更接近根因，后续报错可能只是连锁反应
- 关注组件交界处：例如 HAL / framework / driver / service 的调用边界

### Step 5: 记录日志发现【重要】

用 `upsert_artifact(issue_key, title="log_findings", content=...)` 记录，至少包括：
- 关键错误行或关键日志片段
- 时间线或调用链
- 每条证据对应哪个模块知识点
- 哪些现象已确认，哪些只是待验证假设

要求：
- 日志片段要尽量短而准，避免整段粘贴无关内容
- 结论必须和具体日志行关联，不能只有抽象判断

### Step 6: 查 OpenGrok 代码【重要】

根据 Jira 信息、Confluence 关键词、日志中的函数名/模块名/错误码，调用 OpenGrok 查相关代码。

优先查这些内容：
- 日志打印点
- 错误码定义和返回路径
- 关键函数的调用链
- 与 Jira 组件直接相关的模块

执行要求：
- 先从日志中的唯一字符串、函数名、tag 开始查
- 再向上看调用方和向下看错误返回路径
- 不要泛搜整仓库；每轮查询都要带着明确问题，例如“这个错误是谁打印的”“这个返回码在哪些分支返回”

### Step 7: 记录代码发现【重要】

用 `upsert_artifact(issue_key, title="code_findings", content=...)` 记录，至少包括：
- 可疑文件路径 / 类 / 函数
- 关键代码分支或状态判断
- 日志与代码的对应关系
- 最可能的失效路径
- 修复切入点或需要继续验证的代码问题

### Step 8: 记录分析过程【重要】

用 `upsert_artifact(issue_key, title="analysis_process", content=...)` 记录：
- 初步发现/假设
- 推理过程（如何一步步定位）
- 与文档知识的对照验证
- 与日志证据、代码证据的对应关系
- 被排除掉的假设及排除理由

执行要求：
- `upsert_artifact` 是覆盖式写入；同一个 `title` 应持续整理为最新版，不要反复制造新 title。
- artifact 内容可以直接写原始 markdown / 文本，不需要自己包装表格或额外结构。

### Step 9: 检索本地 history_path

`enter_analyze` 会把整个 `MMAD - Memory - History` 的原始 Confluence storage 内容下载到本地临时文件 `history_path`。需要你自己检索：
- 先用模块名、症状词、错误码、关键 tag 对 `history_path` 做 `grep_files`
- 命中后再用 `read_file` 精读相关条目
- 只能把历史案例当作旁证，不能替代本次 issue 的日志和代码证据
- 在最终结论里明确写出“参考了哪些历史案例，哪些点相似，哪些点不同”

### Step 10: 整理最终结论

在调用 `exit_analyze` 前，先整理一份简短 `conclusion` 段落。建议压缩到几句话，至少覆盖：
- 问题概述
- 根因判断
- 关键证据
- 代码定位
- 修复建议

要求：
- 根因要写成确定性陈述，避免“可能/怀疑/大概”
- 每个关键判断后面都要跟日志或代码依据
- 如果证据不足以支持确定根因，要明确写出“当前只能定位到哪一层”，不要伪造确定性
- 不要把完整推理长文传给 `exit_analyze`；详细内容应该已经沉淀在 artifacts 里

### Step 11: exit_analyze

调用：
```python
exit_analyze(issue_key, conclusion)
```

系统会：
1. 从 `conclusion` 里自动生成一行摘要和 3 个 tags
2. upsert 到 Confluence history
3. 清理下载的附件目录

注意：
- 传入的是简短结论段落，不是 `analysis_struct`
- 在调用前确认 `confluence_notes`、`log_findings`、`code_findings`、`analysis_process` 已用 `upsert_artifact` 更新到最新版
- `exit_analyze` 成功后，本次分析才算真正完成

## 临时工作区

```
.jira-analysis/
└── PROJ-123/
      ├── history.xml                # 从 Confluence 下载的原始 history storage 缓存
      ├── artifacts.xml              # 从 Confluence 下载的原始 artifact storage 缓存
      └── attachments/               # 仅当前分析周期的临时附件
```

持久化位置：
- Artifacts: Confluence 页面 `MMAD - Memory - Artifact - {ISSUE_KEY}`
- History: Confluence history page（只保留 summary 和 tags）

## 关键提醒

1. **先文档、再日志、再代码**：不要一上来就盲搜代码。
2. **4 个笔记要补齐**：`confluence_notes`、`log_findings`、`code_findings`、`analysis_process`。
3. **根因必须有证据链**：至少能串起 Jira 现象、日志片段、代码路径中的两个以上。
4. **历史案例只能辅助**：不能用历史结论替代本次 issue 的证据。
5. **同名 artifact 要覆盖更新**：固定使用标准 title，持续维护最新版。
6. **exit_analyze 是唯一出口**：所有结果必须最终收敛为简短 `conclusion` 并通过它完成 history 沉淀和清理。
