# AIYO

AI automation agent built on `any-llm-sdk`. Supports OpenAI-compatible and Anthropic backends.

## Installation

```bash
# Install dependencies
uv sync

# With dev tools (pytest, black, ruff)
uv sync --extra dev
```

## Configuration

Configuration is loaded from `.env` files (first match wins, highest to lowest priority):

1. `.env` in cwd — project-level overrides
2. `~/.aiyo/.env` — per-user config (recommended for API keys)
3. `/etc/aiyo/aiyo.env` — system-wide defaults (admin-managed)

Minimum required:

```env
PROVIDER=openai
MODEL_NAME=your-model-name
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.example.com/v1   # if using a proxy/SiliconFlow
```

For infrastructure tools (Jira, Confluence, Gerrit), add credentials to `~/.aiyo/.env`:

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

## Usage

### Interactive shell (default)

```bash
uv run aiyo
```

Rich UI with syntax highlighting, bottom status bar, tab completion, and diff display for file edits.

**Slash commands:**

| Command | Action |
|---------|--------|
| `/help` | Show all commands |
| `/reset` | Clear conversation history |
| `/compact` | Compress history (two-layer: micro → deep) |
| `/summary` | Show token usage |
| `/stats` | Show detailed session statistics |
| `/save` | Save history to `.history/` as JSONL |
| `/clear` | Clear screen |
| `/exit` | Exit |

**Keyboard shortcuts:**

| Key | Action |
|-----|--------|
| `Ctrl-C` | Cancel running task (or clear input if idle) |
| `Ctrl-D` | Exit |
| `Shift-Tab` | Toggle plan mode |
| `@filename` | Fuzzy-search files in cwd and attach |
| `@path/to/` | Browse a directory |

**Plan mode** (`Shift-Tab` to toggle): restricts all write operations to the `.plan/` directory and disables shell commands. The agent can only create/edit files under `.plan/`, useful for reviewing a plan before executing it.

### Simple REPL (no Rich UI)

```bash
uv run aiyo repl
```

Same slash commands as the interactive shell, outputs plain text. Useful over SSH or in terminals without full ANSI support.

### Single prompt (scripting/piping)

```bash
uv run aiyo prompt "summarize the build log"
echo "what is 2+2" | uv run aiyo prompt
```

Outputs only the agent's response to stdout — no tool logs, no spinner. Suitable for shell scripts and CI pipelines.

### Other commands

```bash
uv run aiyo info     # show provider/model info
uv run aiyo --debug  # enable debug logging from startup
```

## Skills

Skills inject task-specific instructions into the agent's system prompt without adding new tools. Place `SKILL.md` files in any of (highest to lowest priority, lower-priority directories only add skills not already defined):

1. `./skills/` (relative to `WORK_DIR`) — project-level
2. `~/.aiyo/skills/` — user-level
3. `SKILLS_DIR` env var — additional directory

A skill file uses YAML frontmatter:

```markdown
---
name: my-skill
description: What this skill does
---

Full instructions here. The agent loads this on demand via the `load_skill` tool.
```

Available skills are listed at startup; the agent calls `load_skill("my-skill")` when it determines the skill is relevant.

## Using as a library

```python
from aiyo import Agent

async def main():
    agent = Agent()  # Default tools are built-in
    response = await agent.chat("list files in the current directory")
    print(response)
```

Adding custom middleware:

```python
from aiyo import Middleware, Agent

class MyMiddleware(Middleware):
    def on_tool_call_end(self, tool_name: str, tool_args: dict, result: object) -> object:
        print(f"Tool called: {tool_name}")
        return result

agent = Agent(extra_middleware=[MyMiddleware()])
```

Adding custom tools:

```python
async def my_tool(query: str) -> str:
    """Search internal knowledge base. Requires a search query string."""
    return f"Results for: {query}"

from aiyo import Agent, READ_TOOLS

# Use only read-only tools
agent = Agent(tools=READ_TOOLS)

# Or combine default tools with custom ones
from aiyo.tools import DEFAULT_TOOLS
agent = Agent(tools=DEFAULT_TOOLS + [my_tool])
```

Tool functions must have a **docstring** (used as the tool description) and **type-annotated parameters** (used to generate the JSON schema).

## Development

```bash
uv run pytest tests/ -v                                                    # all tests
uv run pytest tests/test_agent.py::TestAgent::test_tool_is_called -v      # single test
uv run black src/ tests/                                                   # format
uv run ruff check src/ tests/                                              # lint
```
