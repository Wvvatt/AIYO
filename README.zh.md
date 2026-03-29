# AIYO

基于 `any-llm-sdk` 构建的 AI 自动化助手。支持 OpenAI 兼容接口和 Anthropic 后端。

## 项目结构

这是一个 **Monorepo** 多包仓库：

```
AIYO/
├── libs/
│   └── aiyo/              # 核心 Agent 库
├── packages/
│   ├── aiyo-cli/          # 交互式 CLI 工具
│   └── aiyo-server/       # Web API & UI 服务
```

## 安装

### 基础安装

```bash
# 安装所有包（开发模式）
uv pip install -e libs/aiyo -e packages/aiyo-cli -e packages/aiyo-server

# 或使用 uv sync（推荐）
uv sync
```

### 安装扩展工具（可选）

如需使用 Jira、Confluence 和 Gerrit 集成：

```bash
# 安装带 ext 依赖的版本
uv pip install -e "libs/aiyo[ext]" -e packages/aiyo-cli -e packages/aiyo-server

# 或使用 uv sync
uv sync --extra ext
```

然后在 `~/.aiyo/.env` 中配置凭证（详见下方配置部分）。

### 验证安装

```bash
# 检查 ext 工具是否已加载
uv run aiyo info

# 如已安装 ext，应显示：jira_cli, confluence_cli, gerrit_cli
```

要求：Python 3.11+

## 配置

创建 `.env` 文件（或使用 `~/.aiyo/.env` 作为用户级配置）：

```env
# LLM 提供商（openai 或 anthropic）
PROVIDER=openai
MODEL_NAME=gpt-4o-mini
OPENAI_API_KEY=sk-...
# OPENAI_BASE_URL=https://api.example.com/v1  # 可选：用于代理

# 或使用 Anthropic：
# PROVIDER=anthropic
# MODEL_NAME=claude-3-5-sonnet-20241022
# ANTHROPIC_API_KEY=sk-ant-...

# 可选：代理设置（如果在公司防火墙后）
# HTTP_PROXY=http://proxy.example.com:8080
# HTTPS_PROXY=http://proxy.example.com:8080

# 可选：Agent 设置
# AGENT_MAX_ITERATIONS=70
# RESPONSE_TOKEN_LIMIT=8190
# LLM_TIMEOUT=300
# WORK_DIR=/path/to/workspace
```

配置加载顺序（先匹配优先）：
1. 当前目录的 `.env`
2. `~/.aiyo/.env` — 用户级配置（推荐用于存放 API 密钥）
3. `/etc/aiyo/aiyo.env` — 系统级默认配置

### 扩展工具（可选）

如需集成 Jira、Confluence 和 Gerrit，添加到 `~/.aiyo/.env`：

```env
JIRA_SERVER=https://your-jira.example.com
JIRA_USERNAME=your-username
JIRA_PASSWORD=your-password-or-api-token

CONFLUENCE_SERVER=https://your-confluence.example.com
CONFLUENCE_TOKEN=your-personal-access-token

GERRIT_SERVER=https://your-gerrit.example.com
GERRIT_USERNAME=your-username
GERRIT_PASSWORD=your-http-password
```

## 使用

### 交互式 CLI（Shell 模式）

```bash
# 使用 uv run（推荐）
uv run aiyo

# 或虚拟环境已激活时
aiyo
```

提供语法高亮、底部状态栏、Tab 补全和文件编辑差异显示的富文本 UI。

**斜杠命令：**

| 命令 | 操作 |
|---------|--------|
| `/help` | 显示所有命令 |
| `/reset` | 清空对话历史 |
| `/compact` | 压缩历史（两层：micro → deep） |
| `/summary` | 显示 Token 使用量 |
| `/stats` | 显示详细会话统计 |
| `/save` | 保存历史到 `.history/`（JSONL 格式） |
| `/clear` | 清屏 |
| `/exit` | 退出 |

**快捷键：**

| 按键 | 操作 |
|-----|--------|
| `Ctrl-C` | 取消运行中的任务（或空闲时清空输入） |
| `Ctrl-D` | 退出（输入为空时） |
| `Shift-Tab` | 切换计划模式 |
| `@filename` | 模糊搜索当前目录文件并附加 |
| `@path/to/` | 浏览目录 |

**计划模式**（`Shift-Tab` 切换）：将所有写入操作限制在 `.plan/` 目录，并禁用 shell 命令。助手只能创建/编辑 `.plan/` 下的文件，适合在执行前审查计划。

### Web 服务

```bash
# 使用 uv run（推荐）
uv run aiyo-server

# 或虚拟环境已激活时
aiyo-server

# 指定端口
uv run aiyo-server --port 8080

# 开发模式（自动重载）
uv run aiyo-server --reload
```

然后在浏览器打开 http://localhost:8000

Web UI 功能：
- 实时对话，支持 Markdown 渲染
- 工具执行可视化
- 文件上传支持
- 对话重置/压缩控制

### 简单 REPL（无富文本 UI）

```bash
uv run aiyo repl
```

与交互式 Shell 相同的斜杠命令，纯文本输出。适合 SSH 或不完全支持 ANSI 的终端。

### 单条提示（脚本/管道）

```bash
uv run aiyo prompt "总结构建日志"
echo "2+2 等于多少" | uv run aiyo prompt
```

仅将助手回复输出到 stdout — 无工具日志，无转圈等待。适合 shell 脚本和 CI 流水线。

### 其他命令

```bash
uv run aiyo info     # 显示提供商/模型/工具信息
uv run aiyo --debug  # 从启动开始启用调试日志
```

## 工具

AIYO 提供按权限级别组织的内置工具：

### 只读工具

不修改状态的安全操作：

| 工具 | 描述 |
|------|------|
| `get_current_time` | 返回当前日期时间 |
| `think` | 让助手思考问题 |
| `read_file` | 读取文本文件内容 |
| `read_image` | 读取图片文件（多模态支持） |
| `read_pdf` | 从 PDF 提取文本 |
| `list_directory` | 列出目录内容 |
| `glob_files` | 按模式查找文件 |
| `grep_files` | 使用正则搜索文件内容 |
| `fetch_url` | 获取并提取网页内容 |
| `task_create` | 创建追踪任务 |
| `task_get` | 获取任务详情 |
| `task_list` | 列出所有任务 |
| `task_update` | 更新任务状态 |
| `task_delete` | 删除任务 |
| `load_skill` | 加载技能完整指令 |
| `load_skill_resource` | 加载技能资源文件 |
| `ask_user` | 向用户提问（带选项） |

### 写入工具

修改文件或执行命令的操作：

| 工具 | 描述 |
|------|------|
| `write_file` | 创建或覆盖文件 |
| `edit_file` | 编辑文件内容（查找/替换） |
| `shell` | 执行 shell 命令 |

### 编程使用工具

```python
from aiyo import Agent
from aiyo.tools import READ_TOOLS, WRITE_TOOLS

# 仅使用只读工具
agent = Agent()

# 或使用所有默认工具（读 + 写）
agent = Agent(extra_tools=WRITE_TOOLS)
```

## 技能

技能向助手的系统提示词注入任务特定的指令，而不新增工具。将 `SKILL.md` 文件放在以下位置（优先级从高到低，低优先级目录仅添加未定义的skill）：

1. `.aiyo/skills/`（相对于 `WORK_DIR`）— 项目级
2. `~/.aiyo/skills/` — 用户级
3. `SKILLS_DIR` 环境变量 — 额外目录

技能文件使用 YAML 前置元数据：

```markdown
---
name: my-skill
description: 这个技能的作用
---

完整指令写在这里。助手通过 `load_skill` 工具按需加载。
```

启动时会列出可用技能；当助手判断相关时会调用 `load_skill("my-skill")`。

## 作为库使用

### 基础用法

```python
from aiyo import Agent

async def main():
    agent = Agent()  # 内置默认工具
    response = await agent.chat("列出当前目录的文件")
    print(response)
```

### 添加自定义中间件

```python
from aiyo.agent.middleware import Middleware
from aiyo import Agent

class MyMiddleware(Middleware):
    def on_tool_call_end(self, tool_name: str, tool_id: str,
                         tool_args: dict, tool_error: Exception | None,
                         result: object) -> object:
        print(f"工具调用: {tool_name}")
        return result

agent = Agent(extra_middleware=[MyMiddleware()])
```

### 添加自定义工具

```python
async def my_tool(query: str) -> str:
    """搜索内部知识库。需要提供搜索查询字符串。"""
    return f"搜索结果: {query}"

from aiyo import Agent
from aiyo.tools import WRITE_TOOLS

# READ_TOOLS 内置；按需追加写工具/自定义工具
agent = Agent(extra_tools=WRITE_TOOLS + [my_tool])
```

工具函数必须包含 **文档字符串**（用作工具描述）和 **带类型注解的参数**（用于生成 JSON 模式）。

### Agent API 参考

```python
# 核心方法
response = await agent.chat("消息")   # 发送消息，获取回复
agent.reset()                          # 清空历史（保留系统提示词）
agent.toggle_plan_mode()               # 切换计划模式
agent.compact()                        # 压缩历史（两层）
agent.save_history()                   # 保存历史到 .history/

# 属性
agent.model_name                       # 当前模型名称
agent.stats                            # SessionStats 对象
agent.plan_mode                        # 检查计划模式是否激活

# 调试
agent.set_debug(True)                  # 启用调试日志
```

## 故障排查

### 连接失败

如果看到 `Connection failed` 错误：

1. **检查网络连接：**
   ```bash
   curl -I https://api.anthropic.com
   curl -I https://api.openai.com
   ```

2. **检查代理设置**（如果在公司防火墙后）：
   ```bash
   env | grep -i proxy
   ```
   如未设置，添加：
   ```bash
   export HTTP_PROXY=http://proxy.example.com:8080
   export HTTPS_PROXY=http://proxy.example.com:8080
   ```

3. **验证 API 密钥：**
   ```bash
   echo $OPENAI_API_KEY  # 或 $ANTHROPIC_API_KEY
   ```

4. **检查提供商/模型设置：**
   ```bash
   uv run aiyo info
   ```

### 速率限制

如果触发速率限制：
- 稍等片刻后重试
- 检查提供商的速率限制
- 考虑使用不同的模型等级

### Token 超限

如果对话过长：
- 使用 `/compact` 压缩历史
- 使用 `/reset` 重新开始
- 保存上下文到文件并引用

### 权限拒绝

文件操作被限制在 `WORK_DIR`（默认为当前目录）。要访问其他位置的文件：
- 在运行 `aiyo` 前切换到该目录
- 或设置 `WORK_DIR` 环境变量

### 扩展工具不可用

如果 `uv run aiyo info` 没有显示 Jira/Confluence/Gerrit 工具：
- 使用 `uv sync --extra ext` 安装
- 确认 `~/.aiyo/.env` 中的凭证
- 检查服务器 URL 是否正确

## 开发

```bash
# 运行测试
uv run pytest tests/ -v
uv run pytest tests/test_agent.py::TestAgent::test_tool_is_called -v

# 格式化代码
uv run black libs/ packages/ tests/

# 代码检查
uv run ruff check libs/ packages/ tests/
```

## 架构

AIYO 使用基于中间件的架构：

- **Agent**：带工具调用的核心编排循环
- **Middleware**：扩展行为的钩子（日志、统计、压缩、计划模式、视觉）
- **Tools**：文件系统、shell、网页获取、图片/PDF 读取、任务管理、可扩展领域工具
- **History Manager**：长对话的两层压缩（micro → deep），带 Token 计数
- **Stats**：全面的会话统计追踪

详见 `CLAUDE.md` 了解详细架构文档。

## 许可证

MIT 许可证 — 详见 [LICENSE](LICENSE) 文件。
