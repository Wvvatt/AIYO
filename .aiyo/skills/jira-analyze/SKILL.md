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
□ 1. 调用 enter_analyze(issue_key) 获取 Jira 信息
□ 2. 检查 existing_artifacts，如有则 read_artifacts 读取之前的笔记
□ 3.【重要】在 Confluence 页面 "MM+-+AI+Debug+Docs"(pageId=665519915)下匹配模块文档并学习，
□ 4.【重要】分析日志（grep_files 过滤关键词，参考文档中的关键词）
□ 5.【重要】write_artifact 记录从confluence获取的页面ID和模块知识（confluence_notes.md）
□ 6.【重要】write_artifact 记录日志发现（log_findings.md）
□ 7.【重要】write_artifact 记录分析过程（analysis_process.md）
□ 8. 参考 related_cases 历史案例
□ 9. 生成 analysis_struct（summary, root_cause, signals, evidence）
□ 10. 调用 exit_analyze(issue_key, analysis_struct) 完成分析
□ 11. 如 exit_analyze 返回错误，根据 errors 修正后重试
```

**注意：** 步骤 3-7 必须执行，不写笔记的分析过程会丢失！

## 关键约束（违反会导致分析失败）

```
1. 不允许直接输出最终答案到对话
2. 所有产物必须通过 write_artifact 或 exit_analyze 写入
3. exit_analyze 是唯一结束分析的方式
4. analysis_struct.root_cause 禁止使用"可能/怀疑/或许"等不确定表达
5. analysis_struct.evidence 必须包含具体的日志片段
6. exit_analyze 失败时必须根据错误信息补充后重试
```

## 分析流程图

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1: enter_analyze(issue_key)                           │
│  - 获取 Jira 信息、下载附件                                 │
│  - 返回 existing_artifacts（已有笔记）                      │
│  - 返回 related_cases（相关历史案例）                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: 读取已有笔记（如有）                               │
│  read_artifacts(issue_key)                                  │
│  - 避免重复工作，继承之前的分析思路                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: 查 Confluence 模块文档【重要】                     │
│  在 "MM+-+AI+Debug+Docs" 页面下匹配模块                     │
│  - 根据 Issue 组件确定模块名                                │
│  - 获取子页面列表，读取匹配模块的文档                       │
│  - 提取关键调试步骤、错误码、关键词                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 4: 记录 Confluence 知识【重要】                       │
│  write_artifact(name="confluence_notes")                    │
│  - 记录调试步骤、错误码含义、常见原因和解决方案             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 5: 分析日志【重要】                                   │
│  grep_files 过滤关键词（参考文档中的关键词）                │
│  - 小文件：直接读取全文                                     │
│  - 大文件：用文档关键词过滤                                 │
│  - 结合文档知识解读错误含义                                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 6: 记录分析过程【重要】                               │
│  write_artifact(name="analysis_process")                    │
│  - 记录初步发现、推理过程、与文档知识的对照验证             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 7: 记录日志发现【重要】                               │
│  write_artifact(name="log_findings")                      │
│  - 记录关键错误行、错误时间线、与模块文档的对应关系         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 8: 参考 related_cases                                 │
│  - 对比历史相似问题，参考 root_cause 和 fix                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 9: 生成 analysis_struct                               │
│  {                                                          │
│    "summary": "一句话总结(<30字)",                          │
│    "root_cause": "确定性根因（禁止可能/怀疑）",             │
│    "signals": ["错误关键词1", ...],                         │
│    "modules": ["模块名"],                                   │
│    "fix": "修复建议",                                       │
│    "evidence": ["日志片段1", ...]                           │
│  }                                                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 10: exit_analyze(issue_key, analysis_struct)          │
│  - 强校验 analysis_struct                                   │
│  - 生成 analysis.md，更新 history.jsonl                    │
└─────────────────────────────────────────────────────────────┘
```

## 各步骤详解

### Step 1: enter_analyze

获取 Jira 信息和历史数据。注意返回的：
- `existing_artifacts`: 已有笔记列表，有则先读
- `related_cases`: 相关历史案例，后续参考
- `can_reuse_analysis`: 如为 true，直接返回已有分析

### Step 2: 读取已有笔记

如果 `existing_artifacts` 不为空，调用 `read_artifacts` 读取之前的：
- `confluence_notes.md`: 避免重复查 Confluence
- `analysis_process.md`: 继承之前的分析思路
- `log_findings.md`: 了解已定位的关键日志

### Step 3: 查 Confluence 模块文档【重要】

**必须在分析日志之前完成！**

在 "MM+-+AI+Debug+Docs" 页面（ID: 665519915）下：
1. 获取子页面列表
2. 根据 Issue 的组件（components）匹配模块名
3. 读取匹配模块的文档内容
4. 提取：调试步骤、错误码含义、常见原因、关键词

### Step 4: 记录 Confluence 知识【重要】

用 `write_artifact` 写 `confluence_notes.md`，记录：
- 模块关键调试步骤
- 错误码及含义
- 常见原因和解决方案
- 用于 grep 的关键词列表

### Step 5: 分析日志【重要】

带着文档中的关键词去 grep 日志：
```
grep_files(pattern="文档关键词|通用错误词", ...)
```

- 小文件 (< 200KB)：直接读取全文
- 大文件：优先用文档关键词过滤
- 结合文档知识解读错误含义

### Step 6: 记录分析过程【重要】

用 `write_artifact` 写 `analysis_process.md`，记录：
- 初步发现/假设
- 推理过程（如何一步步定位）
- 与文档知识的对照验证

### Step 7: 记录日志发现【重要】

用 `write_artifact` 写 `log_findings.md`，记录：
- 关键错误行（带时间戳）
- 错误时间线
- 与模块文档的对应关系

### Step 8: 参考 related_cases

查看 `enter_analyze` 返回的 `related_cases`：
- `similarity` > 70：高度相关，重点参考
- 对比历史问题的 `root_cause` 和 `fix`
- 在最终分析中体现参考

### Step 9: 生成 analysis_struct

必须包含的字段：
| 字段 | 要求 |
|------|------|
| `summary` | 非空，<30字 |
| `root_cause` | 非空，**禁止**"可能/怀疑/maybe"等词 |
| `signals` | 至少1个错误关键词 |
| `modules` | 涉及的模块列表 |
| `fix` | 修复建议 |
| `evidence` | 非空，具体日志片段 |

### Step 10: exit_analyze

提交 `analysis_struct`，系统会：
1. 强校验（不通过返回 errors，需修正重试）
2. 生成 `analysis.md` 最终报告
3. 追加到 `history.jsonl`

## 目录结构

```
.jira-analysis/
├── history.jsonl                    # 全局历史
└── PROJ-123/
      ├── attachments/               # 下载的附件
      ├── artifacts/                 # 笔记（必须写）
      │   ├── confluence_notes.md    # Confluence 知识
      │   ├── analysis_process.md    # 分析过程
      │   └── log_findings.md        # 日志发现
      ├── pre_jira_info.json         # Jira 快照
      └── analysis.md                # 最终报告
```

## 关键提醒

1. **步骤 3-7 必须执行**：不写笔记 = 分析过程丢失
2. **先查文档再分析日志**：带着关键词去 grep，效率更高
3. **root_cause 必须确定**：禁止"可能/怀疑"，要有日志证据支撑
4. **exit_analyze 是唯一出口**：所有结果必须通过它写入
