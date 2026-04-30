from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# Load order (first match wins, highest to lowest priority):
#   1. .env in cwd          — project-level overrides
#   2. ~/.aiyo/.env         — per-user config (API keys etc.)
#   3. /etc/aiyo/aiyo.env  — system-wide defaults (admin-managed)
load_dotenv()
load_dotenv(Path.home() / ".aiyo" / ".env")
load_dotenv(Path("/etc/aiyo/aiyo.env"))


class Settings(BaseSettings):
    app_name: str = "AIYO"
    app_tagline: str = "Agent In Your Orbit"
    provider: str = "openai"
    model_name: str = "gpt-4o-mini"
    agent_max_iterations: int = 150
    # Maximum tokens for a single LLM response
    response_token_limit: int = 8190
    # Maximum tokens for conversation history
    max_history_tokens: int = 128000
    reserve_tokens: int = 3000
    # LLM API call timeout in seconds
    llm_timeout: int = 300  # 5 minutes
    # All file-system tools are sandboxed to this directory.
    # Set WORK_DIR in .env or the environment to override.
    work_dir: Path = Field(default_factory=Path.cwd)
    # Additional skills directory (lowest priority). When set, it is scanned
    # alongside work_dir/skills (highest) and home/skills (middle).
    skills_dir: Path | None = None
    # Optional MCP config path. If unset, AIYO checks:
    #   1. <work_dir>/.aiyo/mcp.json
    #   2. ~/.aiyo/mcp.json
    mcp_config: Path | None = None


settings = Settings()
