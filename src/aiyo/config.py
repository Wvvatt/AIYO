from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    provider: str = "openai"
    model_name: str = "gpt-4o-mini"
    agent_max_iterations: int = 50
    agent_max_tokens: int = 200000
    agent_system_prompt: str = "You are a helpful AI assistant for Amlogic R&D automation."
    # All file-system tools are sandboxed to this directory.
    # Set WORK_DIR in .env or the environment to override.
    work_dir: Path = Field(default_factory=Path.cwd)
    # Additional skills directory (lowest priority). When set, it is scanned
    # alongside work_dir/skills (highest) and home/skills (middle).
    skills_dir: Path | None = None


settings = Settings()
