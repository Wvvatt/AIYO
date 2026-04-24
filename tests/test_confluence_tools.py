"""Tests for ext.tools.confluence_tools."""

import json
from unittest.mock import MagicMock, patch

import pytest

from aiyo.tools.exceptions import ToolError
from ext.tools.confluence_tools import (
    ConfluenceCredentials,
    confluence_download_attachment,
    confluence_get_attachments,
    confluence_get_page,
    confluence_get_page_by_title,
    confluence_get_page_children,
    confluence_get_spaces,
    confluence_search,
)

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
        with patch("ext.tools.confluence_tools.ConfluenceCredentials", return_value=creds):
            yield confluence


# ---------------------------------------------------------------------------
# Missing env vars
# ---------------------------------------------------------------------------


class TestMissingEnv:
    async def test_missing_username_returns_error(self):
        with patch.dict("os.environ", {"CONFLUENCE_PASSWORD": "x"}, clear=True):
            with pytest.raises(ToolError, match="CREDENTIALS_REQUIRED:"):
                await confluence_get_page("123")

    async def test_missing_password_returns_error(self):
        with patch.dict("os.environ", {"CONFLUENCE_USERNAME": "x"}, clear=True):
            with pytest.raises(ToolError, match="CREDENTIALS_REQUIRED:"):
                await confluence_get_page("123")


# ---------------------------------------------------------------------------
# args as JSON string (LLM serialization quirk)
# ---------------------------------------------------------------------------


class TestArgsAsString:
    # NOTE: JSON string args parsing is not implemented yet
    pass


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
        result = await confluence_search('title ~ "Page"')
        data = json.loads(result)
        assert data["total"] == 1
        assert data["results"][0]["title"] == "Page A"
        mock_confluence.cql.assert_called_once_with('title ~ "Page"', limit=10)

    async def test_respects_limit(self, mock_confluence):
        mock_confluence.cql.return_value = {"results": []}
        await confluence_search("type=page", limit=25)
        mock_confluence.cql.assert_called_once_with("type=page", limit=25)

    async def test_empty_results(self, mock_confluence):
        mock_confluence.cql.return_value = {"results": []}
        result = await confluence_search("project=X")
        assert json.loads(result) == {"total": 0, "results": []}


# ---------------------------------------------------------------------------
# get_page
# ---------------------------------------------------------------------------


class TestGetPage:
    async def test_returns_page_dict(self, mock_confluence):
        mock_confluence.get_page_by_id.return_value = _mock_page("123456", "My Page")
        result = await confluence_get_page("123456")
        data = json.loads(result)
        assert data["id"] == "123456"
        assert data["title"] == "My Page"
        assert data["space"] == "TEAM"
        assert data["body"] == "<p>content</p>"
        mock_confluence.get_page_by_id.assert_called_once_with(
            "123456", expand="body.storage,version,space,ancestors"
        )

    async def test_missing_page_id(self, mock_confluence):
        with pytest.raises(ToolError, match="missing required arg 'page_id'"):
            await confluence_get_page(None)


# ---------------------------------------------------------------------------
# get_page_by_title
# ---------------------------------------------------------------------------


class TestGetPageByTitle:
    async def test_returns_page(self, mock_confluence):
        mock_confluence.get_page_by_title.return_value = _mock_page("999", "Welcome")
        result = await confluence_get_page_by_title("TEAM", "Welcome")
        data = json.loads(result)
        assert data["id"] == "999"
        assert data["title"] == "Welcome"

    async def test_returns_null_when_not_found(self, mock_confluence):
        mock_confluence.get_page_by_title.return_value = None
        result = await confluence_get_page_by_title("TEAM", "Nonexistent")
        assert json.loads(result) is None


class TestGetSpaces:
    async def test_returns_spaces(self, mock_confluence):
        mock_confluence.get_all_spaces.return_value = {
            "results": [
                {"key": "TEAM", "name": "Team Space", "type": "global"},
                {"key": "~user", "name": "User Space", "type": "personal"},
            ]
        }
        result = await confluence_get_spaces()
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
        result = await confluence_get_page_children("100")
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["id"] == "201"
        mock_confluence.get_page_child_by_type.assert_called_once_with("100", type="page", limit=20)


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
        result = await confluence_get_attachments("100")
        data = json.loads(result)
        assert data[0]["id"] == "att1"
        assert data[0]["filename"] == "report.pdf"
        assert data[0]["size"] == 2048

    async def test_no_attachments(self, mock_confluence):
        mock_confluence.get_attachments_from_content.return_value = {"results": []}
        result = await confluence_get_attachments("100")
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
        with patch("ext.tools.confluence_tools.httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.content = b"attachment content"
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = await confluence_download_attachment(
                "100", "att42", save_path=str(dest)
            )

        data = json.loads(result)
        assert data["filename"] == "notes.txt"
        assert data["size"] == 18
        assert dest.read_bytes() == b"attachment content"

    async def test_attachment_not_found(self, mock_confluence):
        mock_confluence.get_attachments_from_content.return_value = {"results": []}
        with pytest.raises(ToolError, match="not found"):
            await confluence_download_attachment("100", "att_missing")

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
        with patch("ext.tools.confluence_tools.httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.content = b"csv,data"
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            with patch("aiyo.config.settings") as mock_settings:
                mock_settings.work_dir = tmp_path
                result = await confluence_download_attachment("100", "att99")

        data = json.loads(result)
        assert data["filename"] == "data.csv"
        assert (tmp_path / "data.csv").read_bytes() == b"csv,data"

