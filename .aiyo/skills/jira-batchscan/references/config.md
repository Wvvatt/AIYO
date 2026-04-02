# Jira Batch Scan 配置文件

## 预置标签 (Predefined Labels)

当前支持的安全 DRM 相关标签：

| 标签名 | 描述 | 适用场景 |
|--------|------|----------|
| `Linux_security_drm` | Linux DRM 安全相关问题 | Linux 平台的 DRM 漏洞、安全补丁、Widevine/PlayReady 安全问题 |
| `android_security_drm` | Android DRM 安全相关问题 | Android 平台的 DRM 漏洞、安全补丁、TEE/SE 安全相关问题 |

### 标签扩展

如需添加更多标签，请在上方表格中添加，并更新交互流程中的选项。

## JQL 模板

### 按标签搜索
```jql
labels in ({{labels}}) 
AND status not in (Closed, Openlinux) 
ORDER BY updated DESC
```

### 按个人搜索
```jql
assignee = {{username}} 
AND status not in (Closed, Openlinux) 
ORDER BY updated DESC
```

### 组合搜索（高级）
```jql
(labels in ({{labels}}) OR assignee in ({{usernames}}))
AND status not in (Closed, Openlinux)
AND priority in ({{priorities}})
ORDER BY updated DESC
```

## 分析参数配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_RESULTS` | 50 | 单次分析最大 Issue 数量 |
| `BATCH_SIZE` | 10 | 每批处理的 Issue 数量 |
| `TIMEOUT_PER_ISSUE` | 300 | 单个 Issue 分析超时时间（秒） |