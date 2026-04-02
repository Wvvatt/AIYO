# Gerrit CLI 命令参考

## 获取变更信息

### get_change
获取变更基本信息。

```python
gerrit_cli("get_change", {"change_id": 634172})
```

返回字段：
- `change_number`: 变更号
- `project`: 项目名称
- `branch`: 目标分支
- `subject`: 提交标题
- `status`: 状态 (NEW, MERGED, ABANDONED)
- `owner`: 作者
- `insertions`: 新增行数
- `deletions`: 删除行数
- `commit`: 提交信息

### get_change_detail
获取变更详情，包括文件列表。

```python
gerrit_cli("get_change_detail", {"change_id": 634172})
```

额外返回：
- `files`: 文件列表，包含 lines_inserted, lines_deleted, status

### get_change_diff
获取 diff 内容（最多 20 个文件）。

```python
gerrit_cli("get_change_diff", {"change_id": 634172})
```

### get_change_messages
获取审查评论历史。

```python
gerrit_cli("get_change_messages", {"change_id": 634172})
```

## 提交审查

### set_review
提交审查意见和评分。

```python
# +1 Code-Review
gerrit_cli("set_review", {
    "change_id": 634172,
    "message": "代码整体良好，建议改进错误处理。",
    "code_review": 1
})

# +2 Code-Review (批准)
gerrit_cli("set_review", {
    "change_id": 634172,
    "message": "LGTM",
    "code_review": 2
})

# -1 Code-Review (需要修改)
gerrit_cli("set_review", {
    "change_id": 634172,
    "message": "需要修改：内存泄漏风险",
    "code_review": -1
})
```

评分值：
- `code_review`: -2 (拒绝), -1 (建议修改), 0 (无意见), +1 (看起来不错), +2 (批准)
- `verified`: -1 (未通过), 0 (未验证), +1 (已验证)

## 其他命令

### list_changes
搜索变更。

```python
gerrit_cli("list_changes", {
    "query": "project:kernel status:open",
    "limit": 25
})
```

### abandon_change
放弃变更。

```python
gerrit_cli("abandon_change", {
    "change_id": 634172,
    "message": "废弃，已重新提交"
})
```

### rebase_change
Rebase 到目标分支最新。

```python
gerrit_cli("rebase_change", {"change_id": 634172})
```

### get_file_content
获取文件内容。

```python
gerrit_cli("get_file_content", {
    "change_id": 634172,
    "file_path": "drivers/foo/bar.c"
})
```
