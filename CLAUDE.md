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
src/aiyo/
├── config.py          # pydantic-settings, reads .env
├── repl.py            # Entry point (uv run aiyo), thin REPL loop
├── slash.py           # Slash command handlers (/stats, /clear, /compact, etc.)
├── session/           # Core agent
│   ├── session.py     # Session class — tool-calling loop
│   ├── history.py     # HistoryManager — token counting, 2-layer compression
│   ├── stats.py       # SessionStats — metrics tracking
│   ├── exceptions.py  # AgentError hierarchy
│   ├── middleware_base.py        # Middleware + MiddlewareChain
│   ├── middleware_compaction.py  # Auto history compaction
│   ├── middleware_logging.py     # Debug logging
│   ├── middleware_stats.py       # Token/timing stats
│   └── middleware_todo.py        # Todo display
└── tools/             # 11 built-in tools
    ├── _sandbox.py    # safe_path() — workspace isolation
    ├── filesystem.py  # read/write/replace/list/glob/grep
    ├── shell.py       # run_shell_command
    ├── web.py         # fetch_url (trafilatura)
    ├── misc.py        # get_current_time, think
    └── todo.py        # todo list management
```

### Session Loop

```
Session.chat(user_message)
  ├── middleware: before_chat
  ├── _run_loop()
  │   └── for iteration in range(max_iterations):
  │       ├── _call_llm()
  │       │   ├── middleware: before_llm_call  ← CompactionMiddleware runs here
  │       │   │   (micro_compact → deep_compact if over token limit)
  │       │   ├── llm.completion(model, messages, tools)
  │       │   └── middleware: after_llm_call
  │       ├── middleware: after_iteration
  │       ├── if tool_calls → _execute_tool() for each → continue loop
  │       └── if no tool_calls → return response
  └── middleware: after_chat
```

### Middleware Hook Chain

| Hook | Threading | Purpose |
|------|-----------|---------|
| `before_chat` | return replaces 1st arg | Modify user message |
| `after_chat` | return replaces 1st arg | Modify response |
| `before_llm_call` | return replaces 1st arg | Modify messages (compaction runs here) |
| `after_llm_call` | return replaces last arg | Modify LLM response |
| `before_tool_call` | return replaces all args | Modify (name, args) tuple |
| `after_tool_call` | return replaces last arg | Modify tool result |
| `after_iteration` | fire-and-forget | Post-iteration side effects |
| `on_error` | fire-and-forget | Error handling |

Chaining rules are in `middleware_base.py` via `_CHAIN_FIRST`, `_CHAIN_LAST`, `_CHAIN_ALL` frozensets.

### History Compression

Two-layer strategy in `HistoryManager`:
- **Layer 1 (micro_compact)**: Replaces old tool results (beyond recent 10) with `[Previous: used tool_name]` placeholders
- **Layer 2 (deep_compact)**: Saves full transcript to `.history/` as JSONL, calls LLM to summarize, replaces history with summary

`HistoryManager` receives the `llm` instance at construction and owns `_summarize()` internally.

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
