---
name: m3mory
description: 使用 AIYO 项目 MCP 配置中的 m3mory 作为长期记忆库。用于搜索历史经验、沉淀 Jira/代码/Confluence/Gerrit 分析结论、导入文档、维护标签和删除过期记忆。
---

# m3mory 使用规范

当任务需要复用或沉淀长期知识时，使用 m3mory。

## 常用接口

- `memory_search(query, mode="semantic"|"exact"|"hybrid", tags=..., time_expr=..., limit=...)`：按语义、精确关键词或混合模式检索。
- `memory_store(content, metadata={"tags": "...", "type": "..."})`：保存短结论、经验、决策或排查记录；写入前必须提取至少 5 个 tags。
- `memory_ingest(file_path=..., tags=[...], memory_type="document")`：导入 Markdown、PDF、TXT、JSON 等文档。
- `memory_list(tags=..., memory_type=..., page=..., page_size=...)`：按分类浏览，不用于主题检索。
- `memory_update(content_hash=..., updates=...)`：修正标签、类型或元数据。
- `memory_delete(...)`：删除明确错误、过期或重复的记忆。
- `memory_health()`：怀疑 m3mory 不可用时先检查健康状态。

## 写入原则

- 只保存可复用知识：根因、证据定位、修复策略、项目背景、关键链接、命令、配置、决策。
- 不保存大段原始日志、整页文档、完整代码块；保存摘要和可定位信息，例如文件路径、函数名、行号、Jira/Gerrit/Confluence 链接。
- 每条记忆应该能独立理解，开头写清主题或对象，例如 `TV-12345: ...`、`webOS26 DRM: ...`。
- 调用 `memory_store` 时必须提取至少 5 个 tags，并通过 `metadata.tags` 传入。tags 优先覆盖：来源类型、任务类型、项目/客户、模块/技术域、issue key/变更号、平台/芯片、关键概念。
- 常用标签：`jira`、`analysis`、`root-cause`、`confluence`、`gerrit`、`opengrok`、模块名、项目名、issue key。
- 发现已有记忆过期或错误时，优先 `memory_update` 或 `memory_delete`，不要留下互相矛盾的重复记录。

## Jira 分析约定

分析 Jira issue 时：

1. 进入分析后，先用 issue key、模块名、错误码、关键日志词搜索 m3mory。
2. 如果命中相似历史案例，再用 Jira/Gerrit/OpenGrok 工具验证相似点，不能只依赖历史记忆下结论。
3. 分析过程中可按阶段保存短记录，例如文档要点、日志定位、可疑代码路径、排除项。
4. 结束前保存一条结构化总结，包含 issue key、现象、根因、关键证据、代码位置、修复建议、相关历史案例。
5. `exit_analyze(issue_key, conclusion)` 只负责收敛摘要和清理本地临时目录；长期沉淀必须通过 m3mory 完成。

## 推荐写入格式

```text
<ISSUE 或主题>: <一句话结论>

Context:
- Project/module: ...
- Symptom: ...

Evidence:
- Log: ...
- Code: ...
- Jira/Gerrit/Confluence: ...

Resolution:
- ...

Tags:
- 至少 5 个，用于传入 `metadata.tags`
```

## 检索策略

- 查历史案例：`memory_search(query="<issue key 或 模块 错误码 现象>", tags="jira,analysis", mode="hybrid", limit=10)`
- 查项目背景：`memory_search(query="<项目名 模块名>", tags="project,confluence", mode="hybrid")`
- 查精确链接或 issue key：`memory_search(query="<exact key>", mode="exact", fallback=True)`
- 结果太少时打开 `fallback=True`，或换用错误码、函数名、客户/项目名再搜一次。
