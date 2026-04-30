"""Credential helpers shared across ext tools."""

from __future__ import annotations

import httpx
from atlassian import Confluence
from jira import JIRA

from ext.config import ExtSettings


class JiraCredentials:
    """Jira auth and client construction."""

    def __init__(self) -> None:
        cfg = ExtSettings()
        self.server = cfg.jira_server
        self.username = cfg.jira_username
        self.password = cfg.jira_password
        if not self.username:
            raise KeyError("JIRA_USERNAME")
        if not self.password:
            raise KeyError("JIRA_PASSWORD")

    def client(self) -> JIRA:
        return JIRA(server=self.server, basic_auth=(self.username, self.password))

    def http_auth(self) -> tuple[str, str]:
        return (self.username, self.password)


class ConfluenceCredentials:
    """Confluence auth and client construction."""

    def __init__(self) -> None:
        cfg = ExtSettings()
        self.server = cfg.confluence_server
        self.token = cfg.confluence_token
        self.username = cfg.confluence_username
        self.password = cfg.confluence_password
        if not self.token and not self.username:
            raise KeyError("CONFLUENCE_TOKEN")
        if not self.token and not self.password:
            raise KeyError("CONFLUENCE_PASSWORD")

    def client(self) -> Confluence:
        if self.token:
            return Confluence(url=self.server, token=self.token)
        return Confluence(url=self.server, username=self.username, password=self.password)

    def http_auth(self) -> tuple[str, str]:
        if self.token:
            return (self.username or "token", self.token)
        return (self.username, self.password)


class GerritCredentials:
    """Gerrit auth and base URL construction."""

    def __init__(self) -> None:
        cfg = ExtSettings()
        self.server = cfg.gerrit_server.rstrip("/")
        self.username = cfg.gerrit_username
        self.password = cfg.gerrit_password
        if not self.username:
            raise KeyError("GERRIT_USERNAME")
        if not self.password:
            raise KeyError("GERRIT_PASSWORD")

    def auth(self) -> httpx.DigestAuth:
        return httpx.DigestAuth(self.username, self.password)

    def base_url(self) -> str:
        return f"{self.server}/a"


__all__ = [
    "ConfluenceCredentials",
    "GerritCredentials",
    "JiraCredentials",
]
