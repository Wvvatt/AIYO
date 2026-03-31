# AIYO

AIYO (Agent In Your Orbit) — AI automation agent built on `any-llm-sdk`. Supports OpenAI-compatible and Anthropic backends.

## Project Structure

This is a **Monorepo** with multiple packages:

```
AIYO/
├── libs/
│   └── aiyo/              # Core agent library
├── packages/
│   ├── aiyo-cli/          # Interactive CLI tool
│   └── aiyo-server/       # Web API & UI server
```

## Installation

### Basic Installation

```bash
# Install all packages in development mode
uv pip install -e libs/aiyo -e packages/aiyo-cli -e packages/aiyo-server

# Or use uv sync (recommended)
uv sync
```

### With Extension Tools (Optional)

For Jira, Confluence, and Gerrit integration:

```bash
# Install with ext dependencies
uv pip install -e "libs/aiyo[ext]" -e packages/aiyo-cli -e packages/aiyo-server

# Or using uv sync
uv sync --extra ext
```

Then configure credentials in `~/.aiyo/.env` (see Configuration section below).

### Verify Installation

```bash
# Check if ext tools are loaded
uv run aiyo info

# Should show: jira_cli, confluence_cli, gerrit_cli (if ext is installed)
```

Requirements: Python 3.11+

## Configuration

Create a `.env` file (or use `~/.aiyo/.env` for per-user config):

```env
# LLM Provider (openai or anthropic)
PROVIDER=openai
MODEL_NAME=gpt-4o-mini
OPENAI_API_KEY=sk-...
# OPENAI_BASE_URL=https://api.example.com/v1  # Optional: for proxies

# Or for Anthropic:
# PROVIDER=anthropic
# MODEL_NAME=claude-3-5-sonnet-20241022
# ANTHROPIC_API_KEY=sk-ant-...

# Optional: Proxy settings (if behind corporate firewall)
# HTTP_PROXY=http://proxy.example.com:8080
# HTTPS_PROXY=http://proxy.example.com:8080

# Optional: Agent settings
# AGENT_MAX_ITERATIONS=70
# RESPONSE_TOKEN_LIMIT=8190
# LLM_TIMEOUT=300
# WORK_DIR=/path/to/workspace
```

Configuration loading order (first match wins):
1. `.env` in current directory
2. `~/.aiyo/.env` — per-user config (recommended for API keys)
3. `/etc/aiyo/aiyo.env` — system-wide defaults

### Extension Tools (Optional)

For Jira, Confluence, and Gerrit integration, add to `~/.aiyo/.env`:

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

### Interactive CLI (Shell Mode)

```bash
# Using uv run (recommended)
uv run aiyo

# Or if virtual environment is activated
aiyo
```

Rich UI with syntax highlighting, bottom status bar, tab completion, and diff display for file edits.

**Slash Commands:**

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

**Keyboard Shortcuts:**

| Key | Action |
|-----|--------|
| `Ctrl-C` | Cancel running task (or clear input if idle) |
| `Ctrl-D` | Exit (when input is empty) |
| `Shift-Tab` | Toggle plan mode |
| `@filename` | Fuzzy-search files in cwd and attach |
| `@path/to/` | Browse a directory |

**Plan Mode** (`Shift-Tab` to toggle): Restricts all write operations to the `.plan/` directory and disables shell commands. The agent can only create/edit files under `.plan/`, useful for reviewing a plan before executing it.

### Web Server

```bash
# Using uv run (recommended)
uv run aiyo-server

# Or if virtual environment is activated
aiyo-server

# With custom port
uv run aiyo-server --port 8080

# Development mode (auto-reload)
uv run aiyo-server --reload
```

Then open http://localhost:8000 in your browser.

The Web UI provides:
- Real-time chat with markdown rendering
- Tool execution visualization
- File upload support
- Conversation reset/compact controls

### Simple REPL (No Rich UI)

```bash
uv run aiyo repl
```

Same slash commands as the interactive shell, outputs plain text. Useful over SSH or in terminals without full ANSI support.

### Single Prompt (Scripting/Piping)

```bash
uv run aiyo prompt "summarize the build log"
echo "what is 2+2" | uv run aiyo prompt
```

Outputs only the agent's response to stdout — no tool logs, no spinner. Suitable for shell scripts and CI pipelines.

### Other Commands

```bash
uv run aiyo info     # show provider/model/tools info
uv run aiyo --debug  # enable debug logging from startup
```

## Tools

AIYO provides built-in tools organized by permission level:

### Read-Only Tools

Safe operations that don't modify state:

| Tool | Description |
|------|-------------|
| `get_current_time` | Returns current date and time |
| `think` | Allows the agent to think through a problem |
| `read_file` | Read text file contents |
| `read_image` | Read image files (multimodal support) |
| `read_pdf` | Extract text from PDF files |
| `list_directory` | List directory contents |
| `glob_files` | Find files matching a pattern |
| `grep_files` | Search file contents with regex |
| `fetch_url` | Fetch and extract web page content |
| `task_create` | Create a tracked task |
| `task_get` | Get task details |
| `task_list` | List all tasks |
| `task_update` | Update task status |
| `task_delete` | Delete a task |
| `load_skill` | Load a skill's full instructions |
| `load_skill_resource` | Load a skill resource file |
| `ask_user` | Ask the user a question with options |

### Write Tools

Operations that modify files or execute commands:

| Tool | Description |
|------|-------------|
| `write_file` | Create or overwrite a file |
| `edit_file` | Edit file contents (search/replace) |
| `shell` | Execute shell commands |

### Using Tools Programmatically

```python
from aiyo import Agent

# Agent uses all built-in tools by default
agent = Agent()

# Or add custom tools
agent = Agent(extra_tools=[my_custom_tool])
```

## Skills

Skills inject task-specific instructions into the agent's system prompt without adding new tools. Place `SKILL.md` files in any of (highest to lowest priority, lower-priority directories only add skills not already defined):

1. `.aiyo/skills/` (relative to `WORK_DIR`) — project-level
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

## Using as a Library

### Basic Usage

```python
from aiyo import Agent

async def main():
    agent = Agent()  # Default tools are built-in
    response = await agent.chat("list files in the current directory")
    print(response)
```

### Adding Custom Middleware

```python
from aiyo.agent.middleware_base import Middleware
from aiyo import Agent

class MyMiddleware(Middleware):
    def on_tool_call_end(self, tool_name: str, tool_id: str, 
                         tool_args: dict, tool_error: Exception | None, 
                         result: object) -> object:
        print(f"Tool called: {tool_name}")
        return result

agent = Agent(extra_middleware=[MyMiddleware()])
```

### Adding Custom Tools

```python
async def my_tool(query: str) -> str:
    """Search internal knowledge base. Requires a search query string."""
    return f"Results for: {query}"

from aiyo import Agent

# All built-in tools are included by default; append custom tools as needed
agent = Agent(extra_tools=[my_tool])
```

Tool functions must have a **docstring** (used as the tool description) and **type-annotated parameters** (used to generate the JSON schema).

### Agent API Reference

```python
# Core methods
response = await agent.chat("message")   # Send message, get response
agent.reset()                            # Clear history (keeps system prompt)
agent.toggle_plan_mode()                 # Toggle plan mode
agent.compact()                          # Compress history (two-layer)
agent.save_history()                     # Save history to .history/

# Properties
agent.model_name                         # Current model name
agent.stats                              # SessionStats object
agent.plan_mode                          # Check if plan mode is active

# Debug
agent.set_debug(True)                    # Enable debug logging
```

## Troubleshooting

### Connection Failed

If you see `Connection failed` error:

1. **Check network connectivity:**
   ```bash
   curl -I https://api.anthropic.com
   curl -I https://api.openai.com
   ```

2. **Check proxy settings** (if behind corporate firewall):
   ```bash
   env | grep -i proxy
   ```
   Set if missing:
   ```bash
   export HTTP_PROXY=http://proxy.example.com:8080
   export HTTPS_PROXY=http://proxy.example.com:8080
   ```

3. **Verify API key:**
   ```bash
   echo $OPENAI_API_KEY  # or $ANTHROPIC_API_KEY
   ```

4. **Check provider/model settings:**
   ```bash
   uv run aiyo info
   ```

### Rate Limiting

If you hit rate limits:
- Wait a moment and retry
- Check your provider's rate limits
- Consider using a different model tier

### Token Limit Exceeded

If conversations get too long:
- Use `/compact` to compress history
- Use `/reset` to start fresh
- Save context to files and reference them

### Permission Denied

File operations are sandboxed to `WORK_DIR` (defaults to current directory). To access files elsewhere:
- Change to that directory before running `aiyo`
- Or set `WORK_DIR` environment variable

### Extension Tools Not Available

If `uv run aiyo info` doesn't show Jira/Confluence/Gerrit tools:
- Install with `uv sync --extra ext`
- Verify credentials in `~/.aiyo/.env`
- Check server URLs are correct

## Development

```bash
# Run tests
uv run pytest tests/ -v
uv run pytest tests/test_agent.py::TestAgent::test_tool_is_called -v

# Format code
uv run black libs/ packages/ tests/

# Lint
uv run ruff check libs/ packages/ tests/
```

## Architecture

AIYO uses a middleware-based architecture:

- **Agent**: Core orchestration loop with tool calling
- **Middleware**: Hooks for extending behavior (logging, stats, compaction, plan mode, vision)
- **Tools**: File system, shell, web fetch, image/PDF reading, task management, and extensible domain tools
- **History Manager**: Two-layer compression (micro → deep) for long conversations with token counting
- **Stats**: Comprehensive session statistics tracking

See `CLAUDE.md` for detailed architecture documentation.

## License

MIT License — see [LICENSE](LICENSE) file for details.
