---
name: m3mory
description: 使用 AIYO 项目 MCP 配置中的 m3mory 作为长期记忆库。用于搜索历史经验、沉淀问题分析、代码、文档和变更结论，导入文档、维护标签和删除过期记忆。
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
- 不保存大段原始日志、整页文档、完整代码块；保存摘要和可定位信息，例如文件路径、函数名、行号、命令、链接。
- 每条记忆应该能独立理解，开头写清主题或对象，例如 `<项目>/<模块>: ...`、`<问题ID>: ...`。
- 调用 `memory_store` 时必须提取至少 5 个 tags，并通过 `metadata.tags` 传入。tags 优先覆盖：来源类型、任务类型、项目/客户、模块/技术域、对象ID/变更号、平台/芯片、关键概念。
- 常用标签：`analysis`、`root-cause`、`decision`、`reference`、`code`、`config`、项目名、模块名、对象ID。
- 发现已有记忆过期或错误时，优先 `memory_update` 或 `memory_delete`，不要留下互相矛盾的重复记录。

## 写入模板

写入时使用一个完整的 `memory_store` 参数模板。正文只放可复用内容；tags 和 type 必须放在 `metadata` 参数里，不要写在正文里。

```python
memory_store(
    content="""<主题或对象>: <一句话结论>

Context:
- Project/module: ...
- Scenario: ...

Evidence:
- Log: ...
- Code: ...
- Command/config/link: ...

Resolution:
- ...
""",
    metadata={
        "tags": "<至少 5 个逗号分隔标签，例如 project,module,analysis,root-cause,key-concept>",
        "type": "<memory type，例如 finding、decision、reference、learning>",
    },
)
```

如果使用 `memory_update` 修正标签，也要把 tags 放进 `updates`：

```python
memory_update(
    content_hash="<hash>",
    updates={
        "tags": "<至少 5 个逗号分隔标签>",
        "memory_type": "<memory type>",
    },
)
```

## 检索策略

- 查历史经验：`memory_search(query="<模块 现象 错误码 关键概念>", tags="analysis,root-cause", mode="hybrid", limit=10)`
- 查项目背景：`memory_search(query="<项目名 模块名>", tags="project,reference", mode="hybrid")`
- 查精确链接或对象ID：`memory_search(query="<exact key>", mode="exact", fallback=True)`
- 结果太少时打开 `fallback=True`，或换用错误码、函数名、客户/项目名再搜一次。
