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
    provider: str = "openai"
    model_name: str = "gpt-4o-mini"
    agent_max_iterations: int = 70
    # LLM 单次响应的最大 token 数
    response_token_limit: int = 8190
    # LLM 调用超时（秒）
    llm_timeout: int = 300  # 5 minutes
    # All file-system tools are sandboxed to this directory.
    # Set WORK_DIR in .env or the environment to override.
    work_dir: Path = Field(default_factory=Path.cwd)
    # Additional skills directory (lowest priority). When set, it is scanned
    # alongside work_dir/skills (highest) and home/skills (middle).
    skills_dir: Path | None = None


settings = Settings()
