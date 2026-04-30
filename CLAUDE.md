# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AIYO** (Agent In Your Orbit) is an AI agent framework for automation, built on `any-llm-sdk` with OpenAI-compatible and Anthropic backends. Python 3.11+, organized as a **uv workspace** with one core library and two consumer packages.

## Workspace Layout

```
AIYO/                                # uv workspace root (not a buildable package)
├── libs/
│   └── aiyo/                        # Core agent library — `aiyo` distribution
│       └── src/
│           ├── aiyo/                # Agent, tools, history, runner, config
│           └── ext/                 # Optional extension tools (Jira, Confluence, Gerrit, analyze)
├── packages/
│   ├── aiyo-cli/                    # Interactive CLI (`uv run aiyo`)
│   │   └── src/aiyo_cli/
│   └── aiyo-server/                 # FastAPI web UI (`uv run aiyo-server`)
│       └── src/aiyo_server/
└── tests/                           # Workspace-level test suite
```

`pyproject.toml` at root only declares `[tool.uv.workspace]` members and tooling config (black, ruff, pytest). Each member has its own `pyproject.toml` with its dependencies.

## Development Commands

```bash
uv sync                                          # install all workspace members
uv sync --extra ext                              # include Jira/Confluence/Gerrit deps
uv run aiyo                                      # interactive shell UI
uv run aiyo repl                                 # plain-text REPL (no Rich)
uv run aiyo prompt "summarize the build log"    # one-shot, stdout-only
uv run aiyo info                                 # show provider/model/tools + ext health
uv run aiyo-server --port 8080                   # web server (default port 8080)

uv run pytest tests/ -v                          # all tests (testpaths=["tests"])
uv run pytest tests/test_agent.py -v             # single file
uv run pytest tests/test_agent.py::TestAgent::test_tool_is_called -v

uv run black libs/ packages/ tests/              # format (line length 100)
uv run ruff check libs/ packages/ tests/         # lint
```

## Architecture

### Core Modules (`libs/aiyo/src/aiyo/`)

```
aiyo/
├── config.py                              # pydantic-settings, .env loader
├── mcp.py                                 # MCP client — McpToolManager, load_mcp_config()
├── agent/
│   ├── agent.py                           # Agent — tool-calling loop
│   ├── history.py                         # HistoryManager + CompactionMiddleware
│   ├── stats.py                           # SessionStats + StatsMiddleware
│   ├── mode.py                            # AgentMode + ModeState + ModeMiddleware
│   ├── exceptions.py                      # AgentError, ToolBlockedError, etc.
│   ├── middleware.py                      # Middleware base + MiddlewareChain
│   └── misc.py                            # LoggingMiddleware, ArgNormalizationMiddleware, VisionMiddleware
├── runner/
│   └── runner.py                          # AgentRunner — queue-based wrapper around Agent
└── tools/
    ├── _sandbox.py                        # safe_path() — workspace isolation under WORK_DIR
    ├── tool_meta.py                       # @tool() decorator — gatherable, not_for_planmode, summary, health_check
    ├── exceptions.py                      # ToolError base exception
    ├── filesystem.py                      # read_file, write_file, edit_file, list/glob/grep
    ├── shell.py                           # shell
    ├── web.py                             # fetch_url (trafilatura)
    ├── image.py                           # read_image (multimodal)
    ├── pdf.py                             # read_pdf
    ├── misc.py                            # get_current_time, think
    ├── todo.py                            # todo_set (single-tool todo list)
    ├── interactive.py                     # ask_user (with Option/Question)
    └── skills.py                          # load_skill, load_skill_resource
```

### Session Loop

```
Agent.chat(user_message)
  ├── middleware: on_chat_start            ← may modify (user_message, tools)
  ├── _run_loop()
  │   └── for iteration in range(max_iterations):
  │       ├── middleware: on_iteration_start    ← CompactionMiddleware runs here
  │       ├── _call_llm()  (with retry + ContextLengthExceeded recovery)
  │       │   └── middleware: on_llm_response
  │       ├── if no tool_calls: handle length-truncation, else return
  │       ├── if tool_calls:
  │       │   ├── partition into read-only (gathered concurrently) and mutation (serial)
  │       │   ├── for each tool_call:
  │       │   │   ├── middleware: on_tool_call_start  (may raise ToolBlockedError)
  │       │   │   ├── execute tool
  │       │   │   └── middleware: on_tool_call_end
  │       │   └── append assistant + tool messages to history
  │       ├── inject progress reminders at 30/60/90% of max_iterations
  │       └── middleware: on_iteration_end
  └── middleware: on_chat_end
```

Read-only tools decorated with `@tool(gatherable=True)` are executed in parallel via `asyncio.gather`; mutation tools run sequentially. The `is_gatherable()` helper queries the `__aiyo_tool_meta__` attribute at runtime. Results are merged back in original order to preserve `tool_call_id` alignment.

The loop also handles:
- **Length truncation** — up to `_MAX_OUTPUT_RECOVERY` (3) "please continue" retries
- **Transient LLM errors** — `_MAX_RETRY_ATTEMPTS` (3) with backoff `(1, 2, 4)`s on `RateLimitError`/`ProviderError`
- **Context overflow** — `ContextLengthExceededError` triggers `deep_compact()` then retries the same iteration
- **Final-iteration guard** — at `max_iterations - 1` injects a "no more tools, summarize now" reminder

### Middleware Hook Chain

Every hook receives a single mutable context dataclass (`ChatStartContext`, `ChatEndContext`, `IterationStartContext`, `LLMResponseContext`, `ToolCallStartContext`, `ToolCallEndContext`, `IterationEndContext`, `ErrorContext`) defined in `agent/middleware.py`. Middleware mutates ctx fields in place and returns `None`.

| Hook | Context fields | Purpose |
|------|----------------|---------|
| `on_chat_start` | `user_message`, `tools` | Modify user message and tools before the loop runs |
| `on_chat_end` | `response` | Modify the final response |
| `on_iteration_start` | `messages` | Modify history (compaction runs here) |
| `on_llm_response` | `messages`, `response` | Modify the LLM response |
| `on_tool_call_start` | `tool_name`, `tool_id`, `tool_args`, `summary` | Modify any field; raise `ToolBlockedError` to abort |
| `on_tool_call_end` | `tool_name`, `tool_id`, `tool_args`, `tool_error`, `result` | Rewrite the result the LLM sees |
| `on_iteration_end` | `iteration`, `messages` | Post-iteration side effects |
| `on_error` | `error`, `context` | Error handling (fire-and-forget) |

`MiddlewareChain.execute_hook(hook_name, ctx)` walks middleware in insertion order, passes the same ctx to each, and returns it. Adding a field to a context never changes hook signatures.

**Default middleware** (added in `Agent.__init__`, in order):
1. `LoggingMiddleware`
2. `StatsMiddleware` (lives in `stats.py`)
3. `CompactionMiddleware` (lives in `history.py`)
4. `VisionMiddleware`
5. `ModeMiddleware` (lives in `mode.py`)
6. `ArgNormalizationMiddleware`

User-supplied middleware (via `extra_middleware=`) is appended after these.

### Agent Modes (`agent/mode.py`)

`AgentMode` enum controls which tools the LLM sees and may call:

| Mode | Behavior |
|------|----------|
| `NORMAL` | Full tool access. |
| `PLAN` | Tools decorated with `@tool(not_for_planmode=True)` (e.g. `shell`) are filtered out; `write_file`/`edit_file` restricted to paths under `.plan/` (enforced via `_is_plan_file` resolution check against `WORK_DIR/.plan`). |

`ModeState` is owned by `Agent` and mutated via `agent.set_mode(mode)`. `ModeMiddleware` reads it on `on_chat_start` (narrows the tool list, injects a one-shot mode-switch system reminder) and `on_tool_call_start` (safety net — raises `ToolBlockedError`).

### History Compression (`agent/history.py`)

`HistoryManager` owns conversation state, token counting (`tiktoken`), and two-layer compression:

- **Layer 1 — `micro_compact`**: Replaces old tool results (beyond the recent 10) with `[Previous: used tool_name]` placeholders.
- **Layer 2 — `deep_compact`**: Saves the full transcript to `.history/` as JSONL, then asks the LLM to summarize and replaces the history with that summary.

`CompactionMiddleware` (defined in the same file) runs at `on_iteration_start`, calling `micro_compact` first and `deep_compact` only when token budget is still over the limit. `HistoryManager` receives the `llm` instance at construction so it can self-summarize without the agent needing to coordinate.

### AgentRunner (`runner/runner.py`)

`AgentRunner` wraps an `Agent` with `asyncio.Queue` based input/output for use by long-running consumers like `aiyo-server`. It owns a worker task, supports cancellation (`cancel_all`), and atomic mode switches (`set_mode` cancels in-flight chats first).

### Tool Metadata (`tools/tool_meta.py`)

The `@tool()` decorator attaches `ToolMeta` to functions via `__aiyo_tool_meta__`:

```python
@tool(gatherable=True, summary=lambda args: f"Reading {args['path']}")
async def read_file(path: str, ...) -> str: ...
```

| Field | Purpose |
|-------|---------|
| `gatherable` | Safe to run concurrently via `asyncio.gather` |
| `not_for_planmode` | Filtered out in `PLAN` mode by `ModeMiddleware` |
| `summary` | Custom one-line summary for UI display |
| `health_check` | Async callable returning status dict for `aiyo info` |

Helpers: `is_gatherable(fn)`, `is_not_for_planmode(fn)`, `get_summary(fn, args)`, `health_check(fn)`.

### Built-in Tools (`tools/__init__.py`)

```python
from aiyo.tools import BUILTIN_TOOLS
```

16 tools, in registration order:

`get_current_time`, `think`, `read_file`, `read_image`, `read_pdf`, `list_directory`, `glob_files`, `grep_files`, `fetch_url`, `todo_set`, `load_skill`, `load_skill_resource`, `ask_user`, `write_file`, `edit_file`, `shell`

All file-operating tools resolve paths through `safe_path()` (`tools/_sandbox.py`) which enforces the `WORK_DIR` sandbox. Tool functions require a **docstring** (used as the tool description) and **type-annotated parameters** (used to generate the JSON schema) — `any-llm-sdk` raises `ValueError` otherwise.

### `ext` Package — Extension Domain Tools

`ext` lives at `libs/aiyo/src/ext/` and is imported with graceful fallback:

```python
try:
    from ext.tools import EXT_TOOLS
except ImportError:
    EXT_TOOLS = []
```

Current `EXT_TOOLS` (32 individual async functions, each using the `@tool()` decorator for metadata):
- **Jira** (7): `jira_search`, `jira_get`, `jira_get_transitions`, `jira_get_projects`, `jira_get_comments`, `jira_get_attachments`, `jira_download_attachment`
- **Confluence** (7): `confluence_search`, `confluence_get_page`, `confluence_get_page_by_title`, `confluence_get_spaces`, `confluence_get_page_children`, `confluence_get_attachments`, `confluence_download_attachment`
- **Gerrit** (8): `gerrit_list_changes`, `gerrit_get_change`, `gerrit_get_change_detail`, `gerrit_get_change_diff`, `gerrit_get_change_messages`, `gerrit_get_file_content`, `gerrit_list_projects`, `gerrit_get_project_branches`
- **OpenGrok** (6): `opengrok_list_projects`, `opengrok_search_code`, `opengrok_search_definition`, `opengrok_search_symbol`, `opengrok_search_path`, `opengrok_read_file`
- **Analyze mode** (3): `enter_analyze`, `upsert_artifact`, `exit_analyze`

Per-tool health checks are embedded via `@tool(health_check=...)` and consumed by `aiyo info`.

### MCP Integration (`mcp.py`)

`McpToolManager` manages connections to external MCP servers (stdio or streamable-http transport). Config is loaded from JSON:

```json
{ "mcpServers": { "server-name": { "command": "...", "args": [...] } } }
```

Config discovery order (first found wins):
1. `mcp_config` setting (explicit path)
2. `<WORK_DIR>/.aiyo/mcp.json`
3. `~/.aiyo/mcp.json`

Each MCP server's tools are dynamically wrapped as async functions with the `@tool()` decorator, making them indistinguishable from built-in tools in the agent loop.

### Skills System (`tools/skills.py`)

Skills inject task-specific instructions into the system prompt without increasing the base tool count. Stored as `SKILL.md` files with YAML frontmatter (`name`, `description`) followed by the full instruction body.

Discovery order (highest to lowest priority — lower-priority directories only contribute skills not already defined):
1. `WORK_DIR/.aiyo/skills/` — project-level
2. `~/.aiyo/skills/` — user-level
3. `SKILLS_DIR` env var — additional directory

Skill descriptions are listed in the system prompt at startup; full content is loaded on demand via `load_skill()`. Skills are hierarchical — a child skill cannot be loaded before its parent.

## CLI Layer (`packages/aiyo-cli/src/aiyo_cli/`)

```
aiyo_cli/
├── __init__.py          # Typer app: default → ShellUI; subcommands: prompt, repl, info
├── cmd_prompt.py        # `prompt` — single prompt, stdout only
├── cmd_repl.py          # `repl` — plain-text REPL (no Rich)
└── ui/
    ├── shell.py         # ShellUI — Rich + prompt-toolkit interactive UI
    ├── completer.py     # AiyoCompleter — fuzzy file completion (@-syntax)
    ├── middleware_tui.py # TUIDisplayMiddleware — diff display, tool call panels
    └── theme.py         # Console theme, palette, token formatting
```

`ShellUI` constructs the `Agent` itself, attaching `EXT_TOOLS` and `EXT_TOOL_MIDDLEWARE + [TUIDisplayMiddleware]`. CLI-level mode is a superset of `AgentMode` (`auto` | `permission` | `plan`) — the `permission` mode maps to `AgentMode.NORMAL` plus a confirmation prompt for write tools.

## Server Layer (`packages/aiyo-server/src/aiyo_server/`)

```
aiyo_server/
├── main.py              # Typer entry: `aiyo-server run --host --port --reload` (default 8080)
├── app.py               # FastAPI app — WebSocket /ws endpoint, static file serving
├── middleware_webui.py  # WebUiDisplayMiddleware — streams tool/response events over WS
└── static/              # Web UI assets (served at /)
```

Environment overrides: `AIYO_SERVER_HOST`, `AIYO_SERVER_PORT`, `AIYO_SERVER_RELOAD`. The server creates a fresh `Agent` per WebSocket connection (not AgentRunner) with `WebUiDisplayMiddleware` streaming events. Write tools (`shell`, `write_file`, `edit_file`) are excluded via `exclude_tools=`.

## Configuration

`.env` load order in `config.py` (first match wins):
1. `.env` in cwd — project-level overrides
2. `~/.aiyo/.env` — per-user (recommended for API keys)
3. `/etc/aiyo/aiyo.env` — system-wide defaults

| Variable | Default | Purpose |
|---|---|---|
| `PROVIDER` | `openai` | LLM provider for `AnyLLM.create()` |
| `MODEL_NAME` | `gpt-4o-mini` | Model identifier |
| `AGENT_MAX_ITERATIONS` | `150` | Tool-call loop cap |
| `RESPONSE_TOKEN_LIMIT` | `8190` | Max tokens per LLM response |
| `MAX_HISTORY_TOKENS` | `200000` | History budget before compaction kicks in |
| `LLM_TIMEOUT` | `300` | LLM call timeout in seconds |
| `WORK_DIR` | cwd | Sandbox root for all file tools |
| `SKILLS_DIR` | `None` | Additional skills directory (lowest priority) |
| `MCP_CONFIG` | `None` | Path to MCP server config JSON (see MCP Integration section) |

API keys (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `ANTHROPIC_API_KEY`, etc.) are read directly from env by `any-llm-sdk`. HTTP proxy variables (`HTTP_PROXY`, `HTTPS_PROXY`) are honored by `httpx` automatically.

### `ext` Configuration (`libs/aiyo/src/ext/config.py`)

| Variable | Purpose |
|---|---|
| `JIRA_SERVER` / `JIRA_USERNAME` / `JIRA_PASSWORD` | Jira credentials |
| `CONFLUENCE_SERVER` / `CONFLUENCE_TOKEN` | PAT (preferred) |
| `CONFLUENCE_USERNAME` / `CONFLUENCE_PASSWORD` | Basic auth fallback |
| `GERRIT_SERVER` / `GERRIT_USERNAME` / `GERRIT_PASSWORD` | Gerrit credentials |
| `OPENGROK_SERVER` | OpenGrok base URL |

## Error Handling

```
AgentError
├── MaxIterationsError       # Loop hit AGENT_MAX_ITERATIONS
└── ContextFilterError       # Wrapped any_llm ContentFilterError

ToolBlockedError             # Not an error — graceful tool blocking by middleware
                             # (caught in _execute_tool, returns e.reason as result)
```

Layering:
- **Tool layer** — let exceptions propagate; `_execute_tool` wraps them as `Error: tool '{name}' failed — {exc}` strings and forwards to `on_tool_call_end` with `tool_error` set.
- **Agent layer** — `_call_llm` retries transient errors, raises `AgentError`/`ContextFilterError` on hard failures; `chat()` catches `MaxIterationsError` and returns a friendly message.
- **UI layer** (`ShellUI`) — catches `Exception` for user-friendly display; detects `ConnectError` patterns and shows network troubleshooting steps without crashing the session.

## Adding Tools

1. Write an async function with a **docstring** (becomes the tool description) and **type-annotated parameters** (becomes the JSON schema). `any-llm-sdk` enforces both.
2. Decorate with `@tool()` from `aiyo.tools.tool_meta` to set metadata: `gatherable=True` for read-only parallel execution, `not_for_planmode=True` to block in PLAN mode, `summary=` for UI display, `health_check=` for `aiyo info`.
3. If the tool reads or writes files, route every path through `safe_path()` from `tools/_sandbox.py`.
4. For built-in tools: add to `BUILTIN_TOOLS` in `tools/__init__.py`.
5. For ext tools: add to `EXT_TOOLS` in `ext/tools/__init__.py`.
6. Multimodal results: return a dict with `type: "image"` or `type: "pdf"` — `_result_to_messages` in `agent.py` handles the OpenAI vision-API formatting.

## Multimodal Support

- **Images** (`read_image`) — returns `{type: "image", path, size, content: <data url>}`. The agent emits a tool message acknowledging the load and a separate user message containing the actual `image_url` (tool messages cannot carry multimodal content per OpenAI spec). `VisionMiddleware` detects whether the active model supports vision.
- **PDFs** (`read_pdf`) — returns `{type: "pdf", path, pages, content}`. Inlined as a single tool message with text extracted via `pypdf`.

## Notes for Future Edits

- The architecture diagram in `README.md` is high-level only — `CLAUDE.md` (this file) is the authoritative reference for module layout.
- When changing the middleware list in `Agent.__init__`, remember default order matters — `CompactionMiddleware` must run before `ModeMiddleware` so the tool list is narrowed against compacted history.
- `tests/` lives at the workspace root, not under each member. `pytest.ini_options` in the root `pyproject.toml` sets `testpaths = ["tests"]`.
- The legacy `tasks.py` module no longer exists — only `todo_set` survives, in `tools/todo.py`.
