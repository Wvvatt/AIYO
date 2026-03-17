# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AIYO** is an AI agent framework for Amlogic R&D automation, built on `any-llm-sdk` with OpenAI/Anthropic backends. Python 3.11+, managed with `uv` and `hatchling`.

## Development Commands

```bash
uv sync --extra dev                     # install deps
uv run aiyo                             # interactive REPL
uv run pytest tests/ -v                 # run all tests
uv run pytest tests/test_agent.py -v    # single file
uv run pytest tests/test_agent.py::TestAgent::test_tool_is_called -v  # single test
uv run black src/ tests/               # format
uv run ruff check src/ tests/          # lint
```

## Architecture

```
src/
├── aiyo/
│   ├── config.py          # pydantic-settings, reads .env
│   ├── agent/             # Core agent
│   │   ├── agent.py       # Agent class — tool-calling loop
│   │   ├── history.py     # HistoryManager — token counting, 2-layer compression
│   │   ├── stats.py       # SessionStats — metrics tracking
│   │   ├── exceptions.py  # AgentError hierarchy
│   │   ├── middleware_base.py        # Middleware + MiddlewareChain
│   │   ├── middleware_cancel.py      # CancelMiddleware — cooperative cancellation
│   │   ├── middleware_compaction.py  # Auto history compaction
│   │   ├── middleware_logging.py     # Debug logging
│   │   └── middleware_stats.py       # Token/timing stats
│   └── tools/             # Built-in tools (READ_TOOLS, WRITE_TOOLS, DEFAULT_TOOLS)
│       ├── _sandbox.py    # safe_path() — workspace isolation
│       ├── filesystem.py  # read/write/replace/list/glob/grep
│       ├── shell.py       # run_shell_command
│       ├── web.py         # fetch_url (trafilatura)
│       ├── misc.py        # get_current_time, think
│       ├── todo.py        # todo list management
│       └── skills.py      # load_skill — on-demand skill loader
├── ext/                   # Extension tools (optional, soft dependency)
│   ├── config.py          # ExtSettings — credentials for Jira/Confluence/Gerrit
│   └── tools/
│       ├── __init__.py    # EXT_TOOLS list: [jira_cli, confluence_cli, gerrit_cli]
│       ├── jira_tools.py  # jira_cli(command, args) → JSON
│       ├── confluence_tools.py  # confluence_cli(command, args) → JSON
│       └── gerrit_tools.py      # gerrit_cli(command, args) → JSON
└── aiyo_cli/              # CLI entry point (uv run aiyo)
    ├── __init__.py        # Typer app; default command launches ShellUI
    ├── cmd_repl.py        # `repl` subcommand — simple REPL, no Rich
    ├── cmd_prompt.py      # `prompt` subcommand — single prompt, stdout only
    └── ui/
        ├── shell.py       # ShellUI — Rich/prompt-toolkit interactive UI
        ├── middleware.py  # DiffMiddleware, PlanModeMiddleware, ToolDisplayMiddleware
        ├── completer.py   # AiyoCompleter — prompt-toolkit autocomplete
        └── theme.py       # Console theme, palette, token formatting
```

### Session Loop

```
Agent.chat(user_message)
  ├── middleware: on_chat_start  ← Modify user message and tools
  ├── _run_loop()
  │   └── for iteration in range(max_iterations):
  │       ├── middleware: on_iteration_start  ← CompactionMiddleware runs here
  │       │   (micro_compact → deep_compact if over token limit)
  │       ├── _call_llm()
  │       │   ├── llm.completion(model, messages, tools)
  │       │   └── middleware: on_llm_response
  │       ├── if no tool_calls → return response
  │       ├── if tool_calls:
  │       │   └── for each tool_call:
  │       │       ├── middleware: on_tool_call_start
  │       │       ├── execute_tool()
  │       │       └── middleware: on_tool_call_end
  │       └── middleware: on_iteration_end
  └── middleware: on_chat_end
```

### Middleware Hook Chain

| Hook | Threading | Purpose |
|------|-----------|---------|
| `on_chat_start` | return replaces all args | Modify user message and tools |
| `on_chat_end` | return replaces 1st arg | Modify response |
| `on_iteration_start` | return replaces 1st arg | Modify messages (compaction runs here) |
| `on_llm_response` | return replaces last arg | Modify LLM response |
| `on_tool_call_start` | return replaces all args | Modify (name, args) tuple |
| `on_tool_call_end` | return replaces last arg | Modify tool result |
| `on_iteration_end` | fire-and-forget | Post-iteration side effects |
| `on_error` | fire-and-forget | Error handling |

Chaining rules are in `middleware_base.py` via `_CHAIN_FIRST`, `_CHAIN_LAST`, `_CHAIN_ALL` frozensets.

### History Compression

Two-layer strategy in `HistoryManager`:
- **Layer 1 (micro_compact)**: Replaces old tool results (beyond recent 10) with `[Previous: used tool_name]` placeholders
- **Layer 2 (deep_compact)**: Saves full transcript to `.history/` as JSONL, calls LLM to summarize, replaces history with summary

`HistoryManager` receives the `llm` instance at construction and owns `_summarize()` internally.

### `ext` Package — Extension Domain Tools

`ext` is an **optional** package imported with graceful fallback:
```python
try:
    from ext.tools import EXT_TOOLS
except ImportError:
    EXT_TOOLS = []
```

At runtime, `ShellUI` combines `DEFAULT_TOOLS + EXT_TOOLS`. Each ext tool follows the **CLI dispatcher pattern**: a single async function with `command: str` and `args: dict` parameters that routes to sub-operations and returns JSON:

```python
async def jira_cli(command: str, args: dict) -> str:
    """..."""  # command examples: "search_issues", "create_issue", "get_issue"
```

### Skills System

Skills inject task-specific instructions into the system prompt without increasing base tool count. Stored as `SKILL.md` files with YAML frontmatter (`name`, `description`) followed by the full instruction body.

Discovery order (first match wins): `WORK_DIR/skills/` → `~/.aiyo/skills/` → `SKILLS_DIR` env var.

Skills are listed in the system prompt on startup; full content is loaded on demand via the `load_skill()` tool during a session.

### Adding Tools

Tool functions require: **docstring** (used as tool description) and **type-annotated parameters** (used for JSON schema). `any-llm-sdk` raises `ValueError` if docstring is missing.

All file-operating tools use `safe_path()` from `tools/_sandbox.py` to enforce `WORK_DIR` sandbox.

## Configuration

`.env` variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `PROVIDER` | `openai` | LLM provider for `AnyLLM.create()` |
| `MODEL_NAME` | `gpt-4o-mini` | Model identifier |
| `AGENT_MAX_ITERATIONS` | `50` | Tool-call loop cap |
| `AGENT_MAX_TOKENS` | `8192` | Max tokens per LLM response |
| `WORK_DIR` | cwd | Sandbox root for file tools |

API keys (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, etc.) are picked up by `any-llm-sdk` directly from env.

### `ext` Configuration (`src/ext/config.py`)

| Variable | Purpose |
|---|---|
| `JIRA_SERVER` | Jira base URL |
| `JIRA_USERNAME` / `JIRA_PASSWORD` | Jira credentials |
| `CONFLUENCE_SERVER` | Confluence base URL |
| `CONFLUENCE_TOKEN` | PAT (preferred over user/pass) |
| `CONFLUENCE_USERNAME` / `CONFLUENCE_PASSWORD` | Confluence basic auth fallback |
| `GERRIT_SERVER` | Gerrit base URL |
| `GERRIT_USERNAME` / `GERRIT_PASSWORD` | Gerrit credentials |

## Exception Hierarchy

```
AgentError
├── ToolExecutionError
├── MaxIterationsError
├── ContextFilterError
├── TokenLimitError
├── ConfigurationError
└── SessionError
```
