"""Extension settings — reads from environment variables (load .env first via load_dotenv).

Usage in Credentials classes:
    cfg = ExtSettings()   # fresh read of current env vars

Call ``load_dotenv()`` once at startup to populate os.environ from .env;
pydantic-settings then reads from os.environ only (no file I/O per call).
"""

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class ExtSettings(BaseSettings):
    # Jira
    jira_server: str = ""
    jira_username: str = ""
    jira_password: str = ""

    # Confluence — use CONFLUENCE_TOKEN (PAT) when available; fall back to
    # CONFLUENCE_USERNAME + CONFLUENCE_PASSWORD for basic auth.
    confluence_server: str = ""
    confluence_token: str = ""  # Personal Access Token (preferred)
    confluence_username: str = ""
    confluence_password: str = ""
    confluence_artifact_page_id: str = ""
    confluence_history_page_id: str = ""

    # Gerrit
    gerrit_server: str = ""
    gerrit_username: str = ""
    gerrit_password: str = ""

    # OpenGrok
    opengrok_server: str = ""

    # env_file=None: .env is loaded once above via load_dotenv();
    # each AmlSettings() call reads from os.environ only, so tests
    # that patch os.environ with clear=True work correctly.
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
