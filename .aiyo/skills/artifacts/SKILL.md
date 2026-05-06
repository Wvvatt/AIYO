---
name: artifacts
description: 管理 AIYO 的 Confluence artifact pages。用于列出 artifact title / section、读取已有 artifact 内容、按 title+section 覆盖更新、删除整页或单个 section，以及在分析类任务中复用统一的 artifact 命名和写入约定。
---

# Artifact 使用规范

当任务需要读写 analyze 相关的持久化 artifacts 时，遵循本 skill。

## 工具语义

- `list_artifacts()`：返回所有 artifact title。
- `list_artifacts(title=...)`：返回该 title 下的 section 列表。
- `get_artifact(title, section="")`：不传 `section` 时读取整个 title；传入 `section` 时只读取该 section。
- `upsert_artifact_section(title, section, content)`：创建或覆盖一个 section；title 不存在时自动创建。
- `delete_artifact(title, section="")`：不传 `section` 时删除整个 title；传入 `section` 时只删除该 section。

## 基本原则

- `title` 表示页面级主题，要尽量通用、可复用，不要机械地每次都绑定到某个 issue。
- 只有内容明确只属于当前 issue 时，才使用 issue 级 title，例如 `PROJ-123`。
- 对跨 issue 的知识，优先使用模块/主题型 title，例如 `decoder-notes`、`audio-pipeline-findings`、`display-timeout-cases`。
- `section` 是 title 内部的稳定键；同一个 `title + section` 应持续整理为最新版，而不是不断制造新 title。
- 在第一次写入前，先检查是否已有可复用 title：先看 `artifact_titles`，必要时再用 `list_artifacts(title=...)` / `get_artifact(...)`。

## 常用 section 约定

- `jira`：只放 Jira / 日志相关链接、路径、关键词、行号，不放大段原文。
- `confluence`：只放 Confluence 页面链接列表和一句话用途说明，不放大段正文。
- `gerrit`：只放代码 / 变更 / 文件链接、函数名、路径、行号，不放大段代码。
- 分析文章可以使用自定义 `section`，但名字要清晰、稳定、可复用。

## 写入要求

- `content` 优先组织成短列表，保留可跳转或可定位的信息。
- 不要把长日志、大段文档、长代码片段直接塞进 artifact。
- 需要保留详细推理时，只写结论、证据定位信息和一句话说明。

## 建议流程

1. 先看 `artifact_titles`，判断是否已有同名或同主题 title。
2. 如需复用某个 title，先用 `list_artifacts(title=...)` 看 section 列表，再按需 `get_artifact(...)`。
3. 写入时优先复用已有 title，并只覆盖需要更新的 section。
4. 若内容已无价值，再用 `delete_artifact(title, section="")` 清理整页或单个 section。
