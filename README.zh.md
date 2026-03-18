# AIYO

基于 `any-llm-sdk` 构建的 AI 自动化助手。支持 OpenAI 兼容接口和 Anthropic 后端。

## 安装

```bash
# 安装依赖
uv sync

# 安装开发工具（pytest、black、ruff）
uv sync --extra dev
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
```

配置加载顺序（先匹配优先）：
1. 当前目录的 `.env`
2. `~/.aiyo/.env` — 用户级配置（推荐用于存放 API 密钥）
3. `/etc/aiyo/aiyo.env` — 系统级默认配置

### 基础设施工具（可选）

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

### 交互式 Shell（默认）

```bash
uv run aiyo
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
| `Ctrl-D` | 退出 |
| `Shift-Tab` | 切换计划模式 |
| `@filename` | 模糊搜索当前目录文件并附加 |
| `@path/to/` | 浏览目录 |

**计划模式**（`Shift-Tab` 切换）：将所有写入操作限制在 `.plan/` 目录，并禁用 shell 命令。助手只能创建/编辑 `.plan/` 下的文件，适合在执行前审查计划。

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
uv run aiyo info     # 显示提供商/模型信息
uv run aiyo --debug  # 从启动开始启用调试日志
```

## 工具

AIYO 提供按权限级别组织的内置工具：

**只读工具**（`READ_TOOLS`）：`get_current_time`、`think`、`read_file`、`list_directory`、`glob_files`、`grep_files`、`fetch_url`、`todo`、`load_skill`、`list_available_skills`

**写入工具**（`WRITE_TOOLS`）：`write_file`、`edit_file`、`shell`

```python
from aiyo import Agent, READ_TOOLS

# 仅使用只读工具
agent = Agent(tools=READ_TOOLS)

# 或使用所有默认工具（读 + 写）
from aiyo.tools import DEFAULT_TOOLS
agent = Agent(tools=DEFAULT_TOOLS)
```

## 技能

技能向助手的系统提示词注入任务特定的指令，而不新增工具。将 `SKILL.md` 文件放在以下位置（优先级从高到低，低优先级目录仅添加未定义的skill）：

1. `./skills/`（相对于 `WORK_DIR`）— 项目级
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

```python
from aiyo import Agent

async def main():
    agent = Agent()  # 内置默认工具
    response = await agent.chat("列出当前目录的文件")
    print(response)
```

添加自定义中间件：

```python
from aiyo import Middleware, Agent

class MyMiddleware(Middleware):
    def on_tool_call_end(self, tool_name: str, tool_args: dict, result: object) -> object:
        print(f"工具调用: {tool_name}")
        return result

agent = Agent(extra_middleware=[MyMiddleware()])
```

添加自定义工具：

```python
async def my_tool(query: str) -> str:
    """搜索内部知识库。需要提供搜索查询字符串。"""
    return f"搜索结果: {query}"

from aiyo import Agent, READ_TOOLS

# 组合默认工具与自定义工具
from aiyo.tools import DEFAULT_TOOLS
agent = Agent(tools=DEFAULT_TOOLS + [my_tool])
```

工具函数必须包含 **文档字符串**（用作工具描述）和 **带类型注解的参数**（用于生成 JSON 模式）。

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

## 开发

```bash
uv run pytest tests/ -v                                                    # 运行所有测试
uv run pytest tests/test_agent.py::TestAgent::test_tool_is_called -v      # 运行单个测试
uv run black src/ tests/                                                   # 格式化代码
uv run ruff check src/ tests/                                              # 代码检查
```

## 架构

AIYO 使用基于中间件的架构：

- **Agent**：带工具调用的核心编排循环
- **Middleware**：扩展行为的钩子（日志、统计、压缩）
- **Tools**：文件系统、shell、网页获取和可扩展的领域工具
- **History Manager**：长对话的两层压缩（micro → deep）

详见 `CLAUDE.md` 了解详细架构文档。
