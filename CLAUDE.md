# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 🤖 项目总结

### 项目概述

**AIYO**（`aiyo`）是一个面向 **Amlogic R&D 自动化**的 AI 智能体（Agent）框架，基于 `any-llm-sdk` 构建，支持 OpenAI / Anthropic 等多种 LLM 后端。项目版本为 `0.1.0`，使用 Python 3.11+。

### 项目结构

```
aiyo/
├── src/aiyo/
│   ├── agent.py        # 核心 Agent 类（工具调用循环）
│   ├── tools.py        # 内置工具集（11 个工具）
│   ├── config.py       # 配置管理（pydantic-settings）
│   ├── cli.py          # 交互式命令行 REPL
│   ├── history.py      # 会话历史管理（含 Token 计数与压缩）
│   ├── middleware.py   # 中间件系统（钩子链）
│   ├── stats.py        # 统计信息收集
│   └── exceptions.py  # 自定义异常层次
├── tests/
│   └── test_agent.py  # 单元测试
├── pyproject.toml     # 项目配置（hatchling 构建）
├── .env.example       # 环境变量模板
├── CLAUDE.md          # 开发指南
└── IMPROVEMENTS.md    # 改进计划文档
```

### 核心架构

**Agent 主循环（`agent.py`）：**

```
Agent.chat(user_message)
  └── _run_loop()
        ├── micro_compact()              # 压缩旧工具结果
        ├── _call_llm(history)           # 调用 LLM
        ├── if tool_calls → _execute_tool() → 追加 tool 消息 → 继续循环
        └── if 无 tool_calls → 返回最终文本
```

最大迭代次数由 `AGENT_MAX_ITERATIONS` 控制（默认 50），超过 Token 限制时自动触发 LLM 摘要压缩。

### 内置工具（`tools.py`，共 11 个）

| 工具 | 功能 |
|------|------|
| `get_current_time` | 获取当前时间 |
| `think` | 内部推理记录 |
| `read_file` | 读取工作区文件 |
| `write_file` | 写入文件（覆盖/追加） |
| `str_replace_file` | 精准字符串替换 |
| `list_directory` | 列出目录内容 |
| `glob_files` | Glob 文件搜索 |
| `grep_files` | 正则内容搜索 |
| `run_shell_command` | 执行 Shell 命令 |
| `fetch_url` | 抓取网页内容 |
| `todo` | 任务列表管理 |

> 所有文件操作均有**沙箱保护**，限制在 `WORK_DIR` 范围内，防止路径逃逸。

### 核心模块说明

**`history.py` - 历史管理：**
- 使用 `tiktoken` 精确统计 Token 数量（降级时按字符估算）
- 两层压缩策略：
  - **Layer 1（micro_compact）**：将旧工具结果替换为简短占位符
  - **Layer 2（deep_compact）**：调用 LLM 生成摘要并保存完整 transcript 到磁盘

**`middleware.py` - 中间件系统：**
支持在以下生命周期钩子注入自定义逻辑：`before_chat` / `after_chat`、`before_llm_call` / `after_llm_call`、`before_tool_call` / `after_tool_call`、`on_error` / `on_iteration_end`。
内置中间件：`LoggingMiddleware`、`StatsMiddleware`、`TodoDisplayMiddleware`、`ValidatorMiddleware`。

**`stats.py` - 统计信息：**
自动追踪消息数量、Token 使用量（输入/输出）、LLM 调用次数及耗时、各工具调用成功率和平均耗时。

**`exceptions.py` - 异常体系：**
```
AgentError (基类)
├── ToolExecutionError   # 工具执行失败
├── MaxIterationsError   # 达到最大迭代次数
├── ContextFilterError   # 内容被安全过滤器拦截
├── TokenLimitError      # Token 超限
├── ConfigurationError   # 配置错误
└── SessionError         # 会话操作失败
```

### CLI 交互命令

通过 `uv run aiyo` 启动交互式 REPL，支持以下斜杠命令：

| 命令 | 功能 |
|------|------|
| `/stats` | 打印统计信息 |
| `/reset-stats` | 重置统计 |
| `/clear` | 清空会话历史 |
| `/history` | 显示历史摘要 |
| `/save` | 保存历史到 `.history/` |
| `/compact` | 触发两层历史压缩 |
| `/debug` | 切换调试日志 |
| `/help` | 显示帮助 |

### 技术依赖

| 依赖 | 用途 |
|------|------|
| `any-llm-sdk` | LLM 统一接口（支持 OpenAI / Anthropic） |
| `pydantic-settings` | 配置管理 |
| `tiktoken` | Token 精确计数 |
| `trafilatura` | 网页内容提取 |
| `httpx` | HTTP 客户端 |
| `python-dotenv` | `.env` 文件加载 |

---

## Development Commands

```bash
# Setup (first time)
uv sync --extra dev

# Run tests
uv run pytest tests/ -v
uv run pytest tests/test_agent.py::TestAgent::test_tool_is_called -v   # single test

# Format / lint
uv run black src/ tests/
uv run ruff check src/ tests/

# Add a dependency
uv add 'any-llm-sdk[anthropic]'

# Interactive CLI
uv run aiyo
```

## Architecture

The package is a single-module Python agent (`src/aiyo/`) built on **any-llm-sdk** with an OpenAI provider.

**Core flow:**

```
Agent.run(user_message)
  └── _loop(messages)
        ├── llm.completion(model, messages, tools=...)   # type: ignore[call-overload]
        ├── if tool_calls → _execute_tool() for each → append role="tool" messages
        └── if no tool_calls → return final text
```

- **`agent.py`** — `Agent` class. Holds a single `AnyLLM` provider instance (`AnyLLM.create("openai")`) reused across all iterations. The `completion()` call requires `# type: ignore[call-overload]` + `cast(ChatCompletion, ...)` because `tools` is only in `acompletion()`'s explicit signature, not in `completion()`'s `@overload` stubs — this is a library limitation, not a bug here.
- **`tools.py`** — Plain Python functions exported as `DEFAULT_TOOLS`. Tool functions **must** have a docstring (any-llm-sdk raises `ValueError` if missing) and type-annotated parameters (used to generate the JSON schema passed to the LLM).
- **`config.py`** — `pydantic-settings` reads `.env`. The OpenAI provider picks up `OPENAI_API_KEY` and `OPENAI_BASE_URL` from the environment automatically; they are declared in `Settings` only for startup validation.
- **`cli.py`** — Thin REPL loop over `Agent.run()`.

## Configuration

Copy `.env.example` to `.env`:

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Required. Also accepted as env var by any-llm-sdk directly. |
| `OPENAI_BASE_URL` | Optional. Override to use an OpenAI-compatible endpoint (e.g. SiliconFlow). |
| `MODEL_NAME` | Model identifier passed to the provider (default: `gpt-4o-mini`). |
| `AGENT_MAX_ITERATIONS` | Hard cap on tool-call loop iterations (default: 20). |

## Adding Tools

A tool is any Python function registered in the `Agent(tools=[...])` constructor:

```python
def my_tool(param: str) -> str:
    """One-line description used as the tool description by the LLM.

    Args:
        param: Description of param (note: any-llm-sdk does NOT parse Args sections —
               parameter descriptions are auto-generated from type annotations).
    """
    ...
```

Requirements: docstring present, all parameters type-annotated. Return value is always stringified before being sent back to the LLM.
