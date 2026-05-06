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
□ 根据jira的基本信息，从confluence查询相关文档和分析经验
□ 分析日志（grep_files 过滤关键词，参考文档中的关键词）
□ 根据jira和log的信息，从opengrok查找相关的代码
□ 从history中查看有没有相似的历史jira issue，如果有，使用jira工具探索一下
□ 按 `artifacts` skill 的规范读取/复用已有 artifact，并沉淀新的分析产物
□ 整理最终结论（结论、根因、证据、修复建议、历史案例参考）
□ 调用 exit_analyze(issue_key, conclusion) 完成分析
```

## 关键约束（违反会导致分析失败）

```
1. 必须按照todo来执行分析过程
2. 所有产物必须通过 artifact tools 或 exit_analyze 写入，artifact 的读取、复用、命名、写入和删除规则统一参考 `.aiyo/skills/artifacts/SKILL.md`。
3. exit_analyze 是唯一结束分析的方式
4. 最终传给 exit_analyze 的必须是简短结论段落，不是 JSON 草稿，也不是长篇调试转录
```

## 步骤详解

### Step 1: enter_analyze

先调用 `enter_analyze(issue_key)`，拿到分析工作区和上下文。

重点阅读以下字段：
- `summary`: Jira 基本信息摘要，包含标题、状态、优先级、组件、标签
- `description`: Jira 描述正文
- `comments`: 评论区内容，常有补充现象、复现步骤、临时结论
- `attachments`: 附件下载结果
- `history_path`: 本地 history 缓存文件路径，内容来自 `jira-history`
- `artifact_titles`: 当前 artifact store 中已有的页面标题列表，但不包含 `jira-history`

执行要求：
- 先快速判断 issue 对应的模块、现象、时间线、是否有日志附件
- artifact 的读取/复用/命名/写入细节遵循 `artifacts` skill
- 如果附件下载失败或没有日志，按 `artifacts` skill 的约定沉淀信息缺口

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

### Step 3: 沉淀相关 Confluence 信息【重要】

按 `artifacts` skill 的规范，把相关 Confluence 页面和用途说明写入合适的 artifact title / section。

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

### Step 5: 查 OpenGrok 代码【重要】

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

### Step 6: 检索 history 并探索相似 Jira issue【重要】

必须对本地 `history_path` 做 grep/read，判断有没有相似的历史 Jira issue。

执行要求：
- 先从模块名、关键词、错误码、现象描述中提取检索词，再对 `history_path` 做检索
- 如果命中了相似案例，提取其中的 Jira issue key、摘要关键词、相似点
- 对命中的历史 issue，不要只停留在 `history.txt`；必须继续使用 Jira 工具做二次探索
- 至少查看相似 issue 的 summary、description、comments、attachments 或其可见元信息
- 重点判断：本次 issue 和历史 issue 是否同模块、同触发条件、同根因、同修复路径
- 如果历史案例不够相似，要明确说明“看过但不能直接复用”的原因

### Step 7: 沉淀 artifacts【重要】

按 `artifacts` skill 的规范，读取/复用已有 artifact，并沉淀新的分析产物。

至少覆盖这些内容：
- Confluence 参考页面和用途说明
- Jira / 评论 / 附件 / 日志定位信息
- 可疑代码 / 搜索结果 / 变更链接 / 文件路径 / 函数名 / 行号
- 初步发现、推理过程、证据对应关系、排除项

### Step 8: 整理最终结论

在调用 `exit_analyze` 前，先整理一份简短 `conclusion` 段落。建议压缩到几句话，至少覆盖：
- 问题概述
- 根因判断
- 关键证据
- 代码定位
- 修复建议
- 历史案例参考（若有）

要求：
- 根因要写成确定性陈述，避免“可能/怀疑/大概”
- 每个关键判断后面都要跟日志或代码依据
- 如果参考了历史 issue，要明确写出“参考了哪些历史案例，哪些点相似，哪些点不同”
- 历史案例只能当作旁证，不能替代本次 issue 的日志和代码证据
- 如果证据不足以支持确定根因，要明确写出“当前只能定位到哪一层”，不要伪造确定性
- 不要把完整推理长文传给 `exit_analyze`；详细内容应该已经沉淀在 artifacts 里

### Step 9: exit_analyze

调用：
```python
exit_analyze(issue_key, conclusion)
```

系统会：
1. 从 `conclusion` 里自动生成一行摘要和 3 个 tags
2. 写入 `jira-history` artifact page
3. 清理下载的附件目录

注意：
- 传入的是简短结论段落，不是 `analysis_struct`
- 在调用前确认相关 section 已按需更新到最新版
- `exit_analyze` 成功后，本次分析才算真正完成

## 临时工作区

```
.jira-analysis/
└── PROJ-123/
      ├── history.txt                # 从 jira-history 下载的本地 history 缓存
      └── attachments/               # 仅当前分析周期的临时附件
```

持久化位置：
- Artifacts: Confluence artifact pages（title 由上下文决定，尽量通用）
- History: artifact page `jira-history`

## 关键提醒

1. **先文档、再日志、再代码**：不要一上来就盲搜代码。
2. **section 要清晰稳定**：`jira`、`confluence`、`gerrit` 是常用建议；分析文章的 section 可以自由发挥，但命名要可读、可复用。
3. **根因必须有证据链**：至少能串起 Jira 现象、日志片段、代码路径中的两个以上。
4. **历史案例只能辅助**：不能用历史结论替代本次 issue 的证据。
5. **优先使用通用 title**：title 要根据上下文创建，尽量通用、可复用；同名 `title + section` 要覆盖更新。
6. **exit_analyze 是唯一出口**：所有结果必须最终收敛为简短 `conclusion` 并通过它完成 history 沉淀和清理。
