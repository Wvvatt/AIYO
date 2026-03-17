"""Tests for aml.tools.jira_tools.jira_cli."""

import json
from unittest.mock import MagicMock, patch

import pytest
from aml.tools.jira_tools import JiraCredentials, jira_cli

ENV = {"JIRA_USERNAME": "testuser", "JIRA_PASSWORD": "testpass"}


def _mock_issue(key="PROJ-1", summary="Test issue"):
    f = MagicMock()
    f.summary = summary
    f.status = "Open"
    f.issuetype = "Bug"
    f.priority = "Major"
    f.assignee = "alice"
    f.reporter = "bob"
    f.created = "2024-01-01"
    f.updated = "2024-01-02"
    f.description = "desc"
    f.labels = []
    f.components = []
    f.fixVersions = []
    issue = MagicMock()
    issue.key = key
    issue.fields = f
    return issue


@pytest.fixture
def mock_jira():
    """Patch JiraCredentials so no real JIRA connection is made."""
    jira = MagicMock()
    creds = MagicMock(spec=JiraCredentials)
    creds.client.return_value = jira
    creds.http_auth.return_value = ("testuser", "testpass")
    with patch.dict("os.environ", ENV):
        with patch("aml.tools.jira_tools.JiraCredentials", return_value=creds):
            yield jira


# ---------------------------------------------------------------------------
# Missing env vars
# ---------------------------------------------------------------------------


class TestMissingEnv:
    async def test_missing_username_returns_error(self):
        with patch.dict("os.environ", {"JIRA_PASSWORD": "x"}, clear=True):
            result = await jira_cli("get", {"issue_key": "PROJ-1"})
        assert result.startswith("Error: missing environment variable")

    async def test_missing_password_returns_error(self):
        with patch.dict("os.environ", {"JIRA_USERNAME": "x"}, clear=True):
            result = await jira_cli("get", {"issue_key": "PROJ-1"})
        assert result.startswith("Error: missing environment variable")


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    async def test_returns_issues(self, mock_jira):
        mock_jira.search_issues.return_value = [_mock_issue("PROJ-1"), _mock_issue("PROJ-2")]
        result = await jira_cli("search", {"jql": "project=PROJ"})
        data = json.loads(result)
        assert data["total"] == 2
        assert data["issues"][0]["key"] == "PROJ-1"
        mock_jira.search_issues.assert_called_once_with("project=PROJ", maxResults=50, fields=None)

    async def test_respects_max_results(self, mock_jira):
        mock_jira.search_issues.return_value = []
        await jira_cli("search", {"jql": "project=X", "max_results": 10})
        mock_jira.search_issues.assert_called_once_with("project=X", maxResults=10, fields=None)

    async def test_respects_fields_filter(self, mock_jira):
        mock_jira.search_issues.return_value = []
        await jira_cli("search", {"jql": "project=X", "fields": ["summary", "status"]})
        mock_jira.search_issues.assert_called_once_with(
            "project=X", maxResults=50, fields="summary,status"
        )

    async def test_empty_result(self, mock_jira):
        mock_jira.search_issues.return_value = []
        result = await jira_cli("search", {"jql": "project=EMPTY"})
        assert json.loads(result) == {"total": 0, "issues": []}


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestGet:
    async def test_returns_issue_dict(self, mock_jira):
        mock_jira.issue.return_value = _mock_issue("PROJ-42", "My issue")
        result = await jira_cli("get", {"issue_key": "PROJ-42"})
        data = json.loads(result)
        assert data["key"] == "PROJ-42"
        assert data["summary"] == "My issue"

    async def test_missing_issue_key(self, mock_jira):
        result = await jira_cli("get", {})
        assert result.startswith("Error: missing required arg")


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_creates_issue(self, mock_jira):
        new_issue = MagicMock()
        new_issue.key = "PROJ-99"
        new_issue.permalink.return_value = "https://jira.example.com/PROJ-99"
        mock_jira.create_issue.return_value = new_issue
        result = await jira_cli(
            "create", {"project": "PROJ", "summary": "New bug", "issue_type": "Bug"}
        )
        data = json.loads(result)
        assert data["created"] == "PROJ-99"
        assert "url" in data

    async def test_create_with_optional_fields(self, mock_jira):
        new_issue = MagicMock()
        new_issue.key = "PROJ-100"
        new_issue.permalink.return_value = "https://jira.example.com/PROJ-100"
        mock_jira.create_issue.return_value = new_issue
        await jira_cli(
            "create",
            {
                "project": "PROJ",
                "summary": "Full issue",
                "description": "desc",
                "priority": "Minor",
                "assignee": "alice",
                "labels": ["lbl"],
                "components": ["Comp"],
            },
        )
        called_fields = mock_jira.create_issue.call_args.kwargs["fields"]
        assert called_fields["description"] == "desc"
        assert called_fields["priority"] == {"name": "Minor"}
        assert called_fields["assignee"] == {"name": "alice"}
        assert called_fields["labels"] == ["lbl"]
        assert called_fields["components"] == [{"name": "Comp"}]


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    async def test_updates_issue(self, mock_jira):
        issue = MagicMock()
        mock_jira.issue.return_value = issue
        result = await jira_cli("update", {"issue_key": "PROJ-1", "fields": {"summary": "Updated"}})
        issue.update.assert_called_once_with(fields={"summary": "Updated"})
        assert "PROJ-1" in result


# ---------------------------------------------------------------------------
# comment
# ---------------------------------------------------------------------------


class TestComment:
    async def test_adds_comment(self, mock_jira):
        comment = MagicMock()
        comment.id = "10001"
        comment.created = "2024-01-01T00:00:00"
        mock_jira.add_comment.return_value = comment
        result = await jira_cli("comment", {"issue_key": "PROJ-1", "body": "Hello"})
        data = json.loads(result)
        assert data["comment_id"] == "10001"
        mock_jira.add_comment.assert_called_once_with("PROJ-1", "Hello")


# ---------------------------------------------------------------------------
# get_transitions / transition
# ---------------------------------------------------------------------------


class TestTransitions:
    async def test_get_transitions(self, mock_jira):
        mock_jira.transitions.return_value = [
            {"id": "1", "name": "To Do"},
            {"id": "2", "name": "In Progress"},
        ]
        result = await jira_cli("get_transitions", {"issue_key": "PROJ-1"})
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["name"] == "To Do"

    async def test_transition_issue(self, mock_jira):
        result = await jira_cli("transition", {"issue_key": "PROJ-1", "transition": "Done"})
        mock_jira.transition_issue.assert_called_once_with("PROJ-1", "Done")
        assert "Done" in result


# ---------------------------------------------------------------------------
# get_projects
# ---------------------------------------------------------------------------


class TestGetProjects:
    async def test_returns_projects(self, mock_jira):
        p1, p2 = MagicMock(), MagicMock()
        p1.key, p1.name = "PROJ", "Project"
        p2.key, p2.name = "DEMO", "Demo"
        mock_jira.projects.return_value = [p1, p2]
        result = await jira_cli("get_projects", {})
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["key"] == "PROJ"


# ---------------------------------------------------------------------------
# get_comments
# ---------------------------------------------------------------------------


class TestGetComments:
    async def test_returns_comments(self, mock_jira):
        c = MagicMock()
        c.id = "20001"
        c.author = "alice"
        c.created = "2024-01-01"
        c.body = "Great work!"
        mock_jira.comments.return_value = [c]
        result = await jira_cli("get_comments", {"issue_key": "PROJ-1"})
        data = json.loads(result)
        assert data[0]["id"] == "20001"
        assert data[0]["body"] == "Great work!"


# ---------------------------------------------------------------------------
# get_attachments
# ---------------------------------------------------------------------------


class TestGetAttachments:
    async def test_returns_attachments(self, mock_jira):
        a = MagicMock()
        a.id = "30001"
        a.filename = "patch.diff"
        a.size = 1024
        a.mimeType = "text/plain"
        a.created = "2024-01-01"
        a.author = "bob"
        a.content = "https://jira.example.com/secure/attachment/30001/patch.diff"
        issue = MagicMock()
        issue.fields.attachment = [a]
        mock_jira.issue.return_value = issue
        result = await jira_cli("get_attachments", {"issue_key": "PROJ-1"})
        data = json.loads(result)
        assert data[0]["id"] == "30001"
        assert data[0]["filename"] == "patch.diff"

    async def test_no_attachments(self, mock_jira):
        issue = MagicMock()
        issue.fields.attachment = []
        mock_jira.issue.return_value = issue
        result = await jira_cli("get_attachments", {"issue_key": "PROJ-1"})
        assert json.loads(result) == []


# ---------------------------------------------------------------------------
# download_attachment
# ---------------------------------------------------------------------------


class TestDownloadAttachment:
    async def test_downloads_to_save_path(self, mock_jira, tmp_path):
        attachment = MagicMock()
        attachment.filename = "report.txt"
        attachment.content = "https://jira.example.com/secure/attachment/40001/report.txt"
        mock_jira.attachment.return_value = attachment

        dest = tmp_path / "report.txt"
        with patch("aml.tools.jira_tools.httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.content = b"file content"
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = await jira_cli(
                "download_attachment",
                {"attachment_id": "40001", "save_path": str(dest)},
            )

        data = json.loads(result)
        assert data["filename"] == "report.txt"
        assert data["size"] == 12
        assert dest.read_bytes() == b"file content"

    async def test_defaults_to_work_dir(self, mock_jira, tmp_path):
        attachment = MagicMock()
        attachment.filename = "log.txt"
        attachment.content = "https://jira.example.com/secure/attachment/40002/log.txt"
        mock_jira.attachment.return_value = attachment

        with patch("aml.tools.jira_tools.httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.content = b"log data"
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            with patch("aiyo.config.settings") as mock_settings:
                mock_settings.work_dir = tmp_path
                result = await jira_cli("download_attachment", {"attachment_id": "40002"})

        data = json.loads(result)
        assert data["filename"] == "log.txt"
        assert (tmp_path / "log.txt").read_bytes() == b"log data"


# ---------------------------------------------------------------------------
# unknown command
# ---------------------------------------------------------------------------


class TestUnknownCommand:
    async def test_unknown_command_returns_error(self, mock_jira):
        result = await jira_cli("fly_to_moon", {})
        assert "Unknown command" in result
        assert "fly_to_moon" in result
