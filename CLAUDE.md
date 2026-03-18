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
│   └── tools/             # Built-in tools
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
  ���       │       ├── execute_tool()
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

Discovery order (highest to lowest priority, lower-priority directories only add skills not already defined):
1. `WORK_DIR/skills/` — project-level skills
2. `~/.aiyo/skills/` — user-level skills
3. `SKILLS_DIR` env var — additional skills directory

Skills are listed in the system prompt on startup; full content is loaded on demand via the `load_skill()` tool during a session.

### Adding Tools

Tool functions require: **docstring** (used as tool description) and **type-annotated parameters** (used for JSON schema). `any-llm-sdk` raises `ValueError` if docstring is missing.

All file-operating tools use `safe_path()` from `tools/_sandbox.py` to enforce `WORK_DIR` sandbox.

#### Tool Categories

```python
from aiyo.tools import READ_TOOLS, WRITE_TOOLS, DEFAULT_TOOLS

READ_TOOLS   # Safe read-only operations
WRITE_TOOLS  # File modification and shell execution
DEFAULT_TOOLS = READ_TOOLS + WRITE_TOOLS  # All built-in tools
```

**READ_TOOLS:** `get_current_time`, `think`, `read_file`, `list_directory`, `glob_files`, `grep_files`, `fetch_url`, `todo`, `load_skill`, `load_skill_resource`

**WRITE_TOOLS:** `write_file`, `str_replace_file`, `shell`

## Configuration

`.env` load order (first match wins, highest to lowest priority):
1. `.env` in cwd — project-level overrides
2. `~/.aiyo/.env` — per-user config (API keys etc.)
3. `/etc/aiyo/aiyo.env` — system-wide defaults (admin-managed)

| Variable | Default | Purpose |
|---|---|---|
| `PROVIDER` | `openai` | LLM provider for `AnyLLM.create()` |
| `MODEL_NAME` | `gpt-4o-mini` | Model identifier |
| `AGENT_MAX_ITERATIONS` | `70` | Tool-call loop cap |
| `RESPONSE_TOKEN_LIMIT` | `8190` | Max tokens per LLM response |
| `WORK_DIR` | cwd | Sandbox root for file tools |
| `SKILLS_DIR` | `None` | Additional skills directory |

API keys (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `ANTHROPIC_API_KEY`, etc.) are picked up by `any-llm-sdk` directly from env.

### Proxy Configuration

If behind a corporate proxy, set these environment variables:

```bash
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080
# or with authentication
export HTTP_PROXY=http://user:pass@proxy.example.com:8080
```

These are read by `httpx` (used by `any-llm-sdk`) automatically.

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

## Error Handling

### Exception Hierarchy

```
AgentError
├── ToolExecutionError
├── MaxIterationsError
├── ContextFilterError
├── TokenLimitError
├── ConfigurationError
└── SessionError

ToolBlockedError  # Not an error; graceful tool blocking by middleware
```

### Connection Error Handling

Network errors (connection failures, timeouts) are caught in `aiyo_cli/ui/shell.py` and displayed as user-friendly messages. The UI layer catches `Exception` and provides helpful diagnostics:

1. Detects `ConnectError` / `Connection error` patterns
2. Displays troubleshooting steps for network issues
3. Allows the user to continue the session instead of crashing

When modifying error handling:
- **UI layer** (`shell.py`): Catch exceptions for user-friendly display
- **Agent layer** (`agent.py`): Catch and wrap LLM errors with context
- **Tool layer**: Let exceptions propagate; they are caught by tool execution wrapper

## Coding Guidelines

### Code Style

- Follow PEP 8
- Use type hints for all function parameters and return values
- Use `black` for formatting (line length 100)
- Use `ruff` for linting
- All public functions must have docstrings

### Error Handling Patterns

```python
# Good: Wrap external errors with context
try:
    result = await external_api.call()
except ExternalError as e:
    raise AgentError(f"Failed to call external API: {e}") from e

# Good: Graceful degradation for optional features
try:
    from ext.tools import EXT_TOOLS
except ImportError:
    EXT_TOOLS = []

# Good: User-facing errors in CLI layer
try:
    response = await agent.chat(message)
except Exception as e:
    console.print(f"[error]Error: {e}[/error]")
    return
```

### Testing

- Write tests for all new tools
- Use `pytest-asyncio` for async tests
- Mock external API calls (LLM, Jira, etc.)
- Test both success and error paths

### Git Workflow

1. Make focused, atomic commits
2. Run tests before committing: `uv run pytest tests/ -v`
3. Run linters: `uv run black src/ tests/ && uv run ruff check src/ tests/`
4. Update documentation if changing behavior

## Troubleshooting

### Connection Errors

If you see `ConnectError: All connection attempts failed`:

1. Check network connectivity: `curl -I https://api.anthropic.com`
2. Verify proxy settings if behind corporate firewall
3. Check API key is set and valid
4. Verify `PROVIDER` and `MODEL_NAME` are correct

### Import Errors for `ext`

The `ext` package is optional. If imports fail:
- Check that `src/ext/` exists
- Verify dependencies in `pyproject.toml` extras
- The main app gracefully handles missing `ext` with `try/except ImportError`

### Token Limit Issues

If hitting token limits:
- Adjust `RESPONSE_TOKEN_LIMIT` in `.env`
- Use `/compact` to compress history
- Reduce context by saving files and referencing them
