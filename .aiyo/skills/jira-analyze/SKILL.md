---
name: jira-analyze
description: 对 Jira Issue 进行深度根因分析并给出修复建议。当用户要求分析某个 Jira issue 时使用此 skill，支持下载 Jira 附件、查询 Confluence 和 OpenGrok、分析日志、定位可疑代码，并用 m3mory 沉淀可复用经验。
---

# Jira Issue 深度分析

## 触发条件

当用户要求以下操作时使用此 skill：
- "分析 Jira issue XXX"
- "帮我看看这个 Jira 问题"
- "对 ISSUE-123 进行根因分析"
- "调查这个 bug"

## Todo List

```
□ 调用 enter_analyze(issue_key) 获取 Jira 信息和临时工作区
□ 用 issue key、模块名、错误码、现象关键词检索 m3mory 历史经验
□ 根据 Jira 基本信息，从 Confluence 查询相关文档和分析经验
□ 分析日志（grep_files 过滤关键词，参考文档中的关键词）
□ 根据 Jira 和 log 信息，从 OpenGrok 查找相关代码
□ 对 m3mory 命中的相似历史 Jira issue 使用 Jira 工具二次验证
□ 按 m3mory skill 的规范沉淀新的分析经验
□ 整理最终结论（结论、根因、证据、修复建议、历史案例参考）
□ 调用 exit_analyze(issue_key, conclusion) 完成分析和本地清理
```

## 关键约束

```
1. 必须按 todo 执行分析过程。
2. 长期经验必须通过 m3mory 写入；搜索、写入、标签和清理规则参考 .aiyo/skills/m3mory/SKILL.md。
3. exit_analyze 是唯一结束分析的方式。
4. 最终传给 exit_analyze 的必须是简短结论段落，不是 JSON 草稿，也不是长篇调试转录。
5. 历史记忆只能辅助，不能替代本次 issue 的日志和代码证据。
```

## Step 1: enter_analyze

先调用 `enter_analyze(issue_key)`，拿到分析工作区和上下文。

重点阅读以下字段：
- `summary`: Jira 基本信息摘要，包含标题、状态、优先级、组件、标签
- `description`: Jira 描述正文
- `comments`: 评论区内容，常有补充现象、复现步骤、临时结论
- `attachments`: 附件下载结果
- `workspace`: `.jira-analysis/<ISSUE>/` 下的本地临时目录

执行要求：
- 快速判断 issue 对应模块、现象、时间线、是否有日志附件。
- 如果附件下载失败或没有日志，按 m3mory 规范沉淀信息缺口。

## Step 2: 检索 m3mory 历史经验

先从 issue key、模块名、关键词、错误码、现象描述中提取检索词，再用 `memory_search`。

执行要求：
- 至少检索一次 `tags="jira,analysis"` 的历史案例。
- 对命中的历史 issue，不要只停留在 m3mory 摘要；必须继续使用 Jira 工具探索 summary、description、comments、attachments 或可见元信息。
- 判断本次 issue 和历史 issue 是否同模块、同触发条件、同根因、同修复路径。
- 如果历史案例不够相似，要说明“看过但不能直接复用”的原因。

## Step 3: 查 Confluence 模块文档

在 "MMAD+-+Docs" 页面（ID: 665519915）下：
1. 获取子页面列表。
2. 根据 Issue 的 components 匹配模块名。
3. 读取匹配模块的文档内容。
4. 提取调试步骤、错误码含义、常见原因、关键词。

执行要求：
- 先按 Jira components、标题关键词、日志中的模块名匹配页面。
- 如果没有精确匹配，找相邻模块、公共调试指南、历史分析经验。
- 至少记录页面 ID、页面标题、为什么相关。
- 不要把整页文档照抄进记忆，只保留后续分析要用的知识点和链接。

## Step 4: 分析日志

优先分析 `attachments` 中 `type=log` 且 `status=downloaded` 的文件。带着文档关键词去筛日志，不要盲读全部附件。

先做两轮检索：
1. 用 Confluence 提取的模块关键词、错误码、关键函数名筛选。
2. 用通用故障词补充筛选：`error` / `fail` / `timeout` / `panic` / `exception` / `warning`。

执行要求：
- 小文件（< 200KB）可直接读取全文。
- 大文件优先用关键词过滤。
- 关注时间顺序：先出现的异常通常更接近根因，后续报错可能只是连锁反应。
- 关注组件交界处，例如 HAL / framework / driver / service 的调用边界。

## Step 5: 查 OpenGrok 代码

根据 Jira 信息、Confluence 关键词、日志中的函数名/模块名/错误码，调用 OpenGrok 查相关代码。

优先查这些内容：
- 日志打印点
- 错误码定义和返回路径
- 关键函数的调用链
- 与 Jira 组件直接相关的模块

每轮查询都要带着明确问题，例如“这个错误是谁打印的”“这个返回码在哪些分支返回”。

## Step 6: 沉淀 m3mory

按 `m3mory` skill 的规范保存可复用经验。至少覆盖：
- Confluence 参考页面和用途说明
- Jira / 评论 / 附件 / 日志定位信息
- 可疑代码 / 搜索结果 / 变更链接 / 文件路径 / 函数名 / 行号
- 初步发现、证据对应关系、排除项
- 最终根因和修复建议

不要保存长日志、整页文档或长代码；保存摘要、定位信息和链接。

## Step 7: 整理最终结论

在调用 `exit_analyze` 前，整理一份简短 `conclusion` 段落，至少覆盖：
- 问题概述
- 根因判断
- 关键证据
- 代码定位
- 修复建议
- 历史案例参考（若有）

要求：
- 根因要写成证据支持的陈述，避免无依据的“可能/怀疑/大概”。
- 每个关键判断后面都要跟日志或代码依据。
- 如果参考了历史 issue，要明确写出哪些案例、哪些点相似、哪些点不同。
- 如果证据不足以支持确定根因，要明确写出“当前只能定位到哪一层”。
- 不要把完整推理长文传给 `exit_analyze`；详细内容应按需沉淀到 m3mory。

## Step 8: exit_analyze

调用：

```python
exit_analyze(issue_key, conclusion)
```

系统会：
1. 从 `conclusion` 里自动生成一行摘要和 3 个 tags。
2. 清理下载的附件目录。

注意：
- 在调用前确认需要长期复用的分析结论已经写入 m3mory。
- `exit_analyze` 成功后，本次分析才算真正完成。

## 临时工作区

```text
.jira-analysis/
└── PROJ-123/
      └── attachments/               # 仅当前分析周期的临时附件
```

持久化位置：
- m3mory：长期分析经验、历史案例、项目背景、链接索引

## 关键提醒

1. 先文档、再日志、再代码，不要一上来就盲搜代码。
2. m3mory 标签要清晰稳定：`jira`、`analysis`、`confluence`、`gerrit`、模块名、项目名、issue key 是常用建议。
3. 根因必须有证据链，至少串起 Jira 现象、日志片段、代码路径中的两个以上。
4. 历史案例只能辅助，不能用历史结论替代本次 issue 的证据。
5. exit_analyze 是唯一出口，所有结果最终收敛为简短 conclusion 并通过它完成本地清理。
