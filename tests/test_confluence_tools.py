"""Tests for aml.tools.confluence_tools.confluence_cli."""

import json
from unittest.mock import MagicMock, patch

import pytest
from aml.tools.confluence_tools import ConfluenceCredentials, confluence_cli

ENV = {
    "CONFLUENCE_USERNAME": "testuser",
    "CONFLUENCE_PASSWORD": "testpass",
}


def _mock_page(page_id="123456", title="Test Page"):
    return {
        "id": page_id,
        "title": title,
        "type": "page",
        "space": {"key": "TEAM"},
        "version": {"number": 3, "by": {"displayName": "Alice"}, "when": "2024-01-01T00:00:00Z"},
        "body": {"storage": {"value": "<p>content</p>"}},
        "ancestors": [{"id": "100", "title": "Parent"}],
        "_links": {"webui": f"/display/TEAM/{title}"},
    }


@pytest.fixture
def mock_confluence():
    """Patch ConfluenceCredentials so no real connection is made."""
    confluence = MagicMock()
    creds = MagicMock(spec=ConfluenceCredentials)
    creds.client.return_value = confluence
    creds.http_auth.return_value = ("testuser", "testpass")
    creds.server = "https://confluence.example.com/"
    with patch.dict("os.environ", ENV):
        with patch("aml.tools.confluence_tools.ConfluenceCredentials", return_value=creds):
            yield confluence


# ---------------------------------------------------------------------------
# Missing env vars
# ---------------------------------------------------------------------------


class TestMissingEnv:
    async def test_missing_username_returns_error(self):
        with patch.dict("os.environ", {"CONFLUENCE_PASSWORD": "x"}, clear=True):
            result = await confluence_cli("get_page", {"page_id": "123"})
        assert result.startswith("Error: missing environment variable")

    async def test_missing_password_returns_error(self):
        with patch.dict("os.environ", {"CONFLUENCE_USERNAME": "x"}, clear=True):
            result = await confluence_cli("get_page", {"page_id": "123"})
        assert result.startswith("Error: missing environment variable")


# ---------------------------------------------------------------------------
# args as JSON string (LLM serialization quirk)
# ---------------------------------------------------------------------------


class TestArgsAsString:
    async def test_args_as_json_string(self, mock_confluence):
        mock_confluence.get_page_by_id.return_value = _mock_page()
        result = await confluence_cli("get_page", '{"page_id": "123456"}')
        assert json.loads(result)["id"] == "123456"

    async def test_invalid_json_string_returns_error(self, mock_confluence):
        result = await confluence_cli("get_page", "not-valid-json")
        assert result.startswith("Error: args is not valid JSON")


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    async def test_returns_results(self, mock_confluence):
        mock_confluence.cql.return_value = {
            "results": [
                {
                    "content": {"id": "1", "title": "Page A", "type": "page"},
                    "resultGlobalContainer": {"title": "TEAM"},
                    "url": "/pages/1",
                    "lastModified": "2024-01-01",
                    "excerpt": "...",
                }
            ]
        }
        result = await confluence_cli("search", {"cql": 'title ~ "Page"'})
        data = json.loads(result)
        assert data["total"] == 1
        assert data["results"][0]["title"] == "Page A"
        mock_confluence.cql.assert_called_once_with('title ~ "Page"', limit=10)

    async def test_respects_limit(self, mock_confluence):
        mock_confluence.cql.return_value = {"results": []}
        await confluence_cli("search", {"cql": "type=page", "limit": 25})
        mock_confluence.cql.assert_called_once_with("type=page", limit=25)

    async def test_empty_results(self, mock_confluence):
        mock_confluence.cql.return_value = {"results": []}
        result = await confluence_cli("search", {"cql": "project=X"})
        assert json.loads(result) == {"total": 0, "results": []}


# ---------------------------------------------------------------------------
# get_page
# ---------------------------------------------------------------------------


class TestGetPage:
    async def test_returns_page_dict(self, mock_confluence):
        mock_confluence.get_page_by_id.return_value = _mock_page("123456", "My Page")
        result = await confluence_cli("get_page", {"page_id": "123456"})
        data = json.loads(result)
        assert data["id"] == "123456"
        assert data["title"] == "My Page"
        assert data["space"] == "TEAM"
        assert data["body"] == "<p>content</p>"
        mock_confluence.get_page_by_id.assert_called_once_with(
            "123456", expand="body.storage,version,space,ancestors"
        )

    async def test_missing_page_id(self, mock_confluence):
        result = await confluence_cli("get_page", {})
        assert result.startswith("Error: missing required arg")


# ---------------------------------------------------------------------------
# get_page_by_title
# ---------------------------------------------------------------------------


class TestGetPageByTitle:
    async def test_returns_page(self, mock_confluence):
        mock_confluence.get_page_by_title.return_value = _mock_page("999", "Welcome")
        result = await confluence_cli(
            "get_page_by_title", {"space_key": "TEAM", "title": "Welcome"}
        )
        data = json.loads(result)
        assert data["id"] == "999"
        assert data["title"] == "Welcome"

    async def test_returns_null_when_not_found(self, mock_confluence):
        mock_confluence.get_page_by_title.return_value = None
        result = await confluence_cli(
            "get_page_by_title", {"space_key": "TEAM", "title": "Nonexistent"}
        )
        assert json.loads(result) is None


# ---------------------------------------------------------------------------
# create_page
# ---------------------------------------------------------------------------


class TestCreatePage:
    async def test_creates_page(self, mock_confluence):
        new_page = {
            "id": "777",
            "title": "New Page",
            "_links": {"webui": "/display/TEAM/New+Page"},
        }
        mock_confluence.create_page.return_value = new_page
        result = await confluence_cli(
            "create_page",
            {"space_key": "TEAM", "title": "New Page", "body": "<p>hello</p>"},
        )
        data = json.loads(result)
        assert data["created"] == "777"
        assert data["title"] == "New Page"
        mock_confluence.create_page.assert_called_once_with(
            space="TEAM",
            title="New Page",
            body="<p>hello</p>",
            parent_id=None,
            representation="storage",
        )

    async def test_creates_page_with_parent(self, mock_confluence):
        new_page = {"id": "778", "title": "Child", "_links": {"webui": "/child"}}
        mock_confluence.create_page.return_value = new_page
        await confluence_cli(
            "create_page",
            {"space_key": "TEAM", "title": "Child", "body": "", "parent_id": "100"},
        )
        called = mock_confluence.create_page.call_args.kwargs
        assert called["parent_id"] == "100"


# ---------------------------------------------------------------------------
# update_page
# ---------------------------------------------------------------------------


class TestUpdatePage:
    async def test_updates_page(self, mock_confluence):
        current = _mock_page("123", "Old Title")
        updated = {
            "id": "123",
            "title": "New Title",
            "version": {"number": 4},
            "_links": {"webui": "/New+Title"},
        }
        mock_confluence.get_page_by_id.return_value = current
        mock_confluence.update_page.return_value = updated
        result = await confluence_cli(
            "update_page", {"page_id": "123", "title": "New Title", "body": "<p>updated</p>"}
        )
        data = json.loads(result)
        assert data["updated"] == "123"
        assert data["title"] == "New Title"
        assert data["version"] == 4


# ---------------------------------------------------------------------------
# get_spaces
# ---------------------------------------------------------------------------


class TestGetSpaces:
    async def test_returns_spaces(self, mock_confluence):
        mock_confluence.get_all_spaces.return_value = {
            "results": [
                {"key": "TEAM", "name": "Team Space", "type": "global"},
                {"key": "~user", "name": "User Space", "type": "personal"},
            ]
        }
        result = await confluence_cli("get_spaces", {})
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["key"] == "TEAM"


# ---------------------------------------------------------------------------
# get_page_children
# ---------------------------------------------------------------------------


class TestGetPageChildren:
    async def test_returns_children(self, mock_confluence):
        mock_confluence.get_page_child_by_type.return_value = [
            {"id": "201", "title": "Child A", "_links": {"webui": "/Child+A"}},
            {"id": "202", "title": "Child B", "_links": {"webui": "/Child+B"}},
        ]
        result = await confluence_cli("get_page_children", {"page_id": "100"})
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["id"] == "201"
        mock_confluence.get_page_child_by_type.assert_called_once_with("100", type="page", limit=20)


# ---------------------------------------------------------------------------
# get_comments
# ---------------------------------------------------------------------------


class TestGetComments:
    async def test_returns_comments(self, mock_confluence):
        mock_confluence.get_page_comments.return_value = {
            "results": [
                {
                    "id": "c1",
                    "version": {
                        "by": {"displayName": "Bob"},
                        "when": "2024-01-02",
                    },
                    "body": {"view": {"value": "Nice work!"}},
                }
            ]
        }
        result = await confluence_cli("get_comments", {"page_id": "100"})
        data = json.loads(result)
        assert data[0]["id"] == "c1"
        assert data[0]["body"] == "Nice work!"


# ---------------------------------------------------------------------------
# add_comment
# ---------------------------------------------------------------------------


class TestAddComment:
    async def test_adds_comment(self, mock_confluence):
        mock_confluence.add_comment.return_value = {
            "id": "c99",
            "version": {"when": "2024-01-03"},
        }
        result = await confluence_cli("add_comment", {"page_id": "100", "body": "Hello!"})
        data = json.loads(result)
        assert data["comment_id"] == "c99"
        mock_confluence.add_comment.assert_called_once_with("100", "Hello!")


# ---------------------------------------------------------------------------
# get_attachments
# ---------------------------------------------------------------------------


class TestGetAttachments:
    async def test_returns_attachments(self, mock_confluence):
        mock_confluence.get_attachments_from_content.return_value = {
            "results": [
                {
                    "id": "att1",
                    "title": "report.pdf",
                    "metadata": {"mediaType": "application/pdf"},
                    "extensions": {"fileSize": 2048},
                    "version": {
                        "when": "2024-01-01",
                        "by": {"displayName": "Carol"},
                    },
                    "_links": {"download": "/download/att1/report.pdf"},
                }
            ]
        }
        result = await confluence_cli("get_attachments", {"page_id": "100"})
        data = json.loads(result)
        assert data[0]["id"] == "att1"
        assert data[0]["filename"] == "report.pdf"
        assert data[0]["size"] == 2048

    async def test_no_attachments(self, mock_confluence):
        mock_confluence.get_attachments_from_content.return_value = {"results": []}
        result = await confluence_cli("get_attachments", {"page_id": "100"})
        assert json.loads(result) == []


# ---------------------------------------------------------------------------
# download_attachment
# ---------------------------------------------------------------------------


class TestDownloadAttachment:
    async def test_downloads_to_save_path(self, mock_confluence, tmp_path):
        mock_confluence.get_attachments_from_content.return_value = {
            "results": [
                {
                    "id": "att42",
                    "title": "notes.txt",
                    "metadata": {},
                    "extensions": {},
                    "version": {"when": "2024-01-01", "by": {"displayName": "Dave"}},
                    "_links": {"download": "/download/att42/notes.txt"},
                }
            ]
        }
        dest = tmp_path / "notes.txt"
        with patch("aml.tools.confluence_tools.httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.content = b"attachment content"
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = await confluence_cli(
                "download_attachment",
                {
                    "page_id": "100",
                    "attachment_id": "att42",
                    "save_path": str(dest),
                },
            )

        data = json.loads(result)
        assert data["filename"] == "notes.txt"
        assert data["size"] == 18
        assert dest.read_bytes() == b"attachment content"

    async def test_attachment_not_found(self, mock_confluence):
        mock_confluence.get_attachments_from_content.return_value = {"results": []}
        result = await confluence_cli(
            "download_attachment",
            {"page_id": "100", "attachment_id": "att_missing"},
        )
        assert "not found" in result

    async def test_defaults_to_work_dir(self, mock_confluence, tmp_path):
        mock_confluence.get_attachments_from_content.return_value = {
            "results": [
                {
                    "id": "att99",
                    "title": "data.csv",
                    "metadata": {},
                    "extensions": {},
                    "version": {"when": "2024-01-01", "by": {"displayName": "Eve"}},
                    "_links": {"download": "/download/att99/data.csv"},
                }
            ]
        }
        with patch("aml.tools.confluence_tools.httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.content = b"csv,data"
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            with patch("aiyo.config.settings") as mock_settings:
                mock_settings.work_dir = tmp_path
                result = await confluence_cli(
                    "download_attachment",
                    {"page_id": "100", "attachment_id": "att99"},
                )

        data = json.loads(result)
        assert data["filename"] == "data.csv"
        assert (tmp_path / "data.csv").read_bytes() == b"csv,data"


# ---------------------------------------------------------------------------
# unknown command
# ---------------------------------------------------------------------------


class TestUnknownCommand:
    async def test_unknown_command_returns_error(self, mock_confluence):
        result = await confluence_cli("teleport", {})
        assert "Unknown command" in result
        assert "teleport" in result
