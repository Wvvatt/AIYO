"""Tests for ext.tools.gerrit_tools."""

import base64
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from aiyo.tools.exceptions import ToolError
from ext.tools.gerrit_tools import (
    gerrit_get_change,
    gerrit_get_change_detail,
    gerrit_get_change_messages,
    gerrit_get_file_content,
    gerrit_get_project_branches,
    gerrit_list_changes,
    gerrit_list_projects,
)

ENV = {
    "GERRIT_USERNAME": "testuser",
    "GERRIT_PASSWORD": "testpass",
}

# Gerrit magic prefix prepended to every JSON response
_MAGIC = b")]}'\n"

_CHANGE = {
    "id": "platform%2Fkernel~main~I1234567890abcdef",
    "_number": 448402,
    "project": "platform/kernel",
    "branch": "main",
    "subject": "Fix null deref in foo",
    "status": "NEW",
    "owner": {"name": "Alice"},
    "created": "2024-01-01 00:00:00.000000000",
    "updated": "2024-01-02 00:00:00.000000000",
    "insertions": 10,
    "deletions": 2,
    "topic": None,
    "hashtags": [],
    "labels": {
        "Code-Review": {"approved": {"name": "Bob"}},
        "Verified": {},
    },
    "current_revision": "abc123",
    "revisions": {
        "abc123": {
            "_number": 3,
            "ref": "refs/changes/02/448402/3",
            "commit": {
                "subject": "Fix null deref in foo",
                "message": "Fix null deref in foo\n\nChange-Id: I1234567890\n",
                "author": {"name": "Alice"},
                "committer": {"name": "Alice"},
            },
        }
    },
}


_DUMMY_REQUEST = httpx.Request("GET", "https://gerrit.example.com/a/")


def _resp(data: object, status_code: int = 200) -> httpx.Response:
    """Build a fake httpx.Response with Gerrit magic prefix."""
    body = _MAGIC + json.dumps(data).encode()
    return httpx.Response(status_code, content=body, request=_DUMMY_REQUEST)


def _plain_resp(content: bytes, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, content=content, request=_DUMMY_REQUEST)


def _no_content_resp() -> httpx.Response:
    return httpx.Response(204, request=_DUMMY_REQUEST)


@pytest.fixture
def mock_client():
    """Patch httpx.Client so no real HTTP calls are made."""
    client = MagicMock()
    client.__enter__ = lambda s: s
    client.__exit__ = MagicMock(return_value=False)
    with patch.dict("os.environ", ENV):
        with patch("ext.tools.gerrit_tools.httpx.Client", return_value=client):
            yield client


# ---------------------------------------------------------------------------
# Missing env vars
# ---------------------------------------------------------------------------


class TestMissingEnv:
    async def test_missing_username(self):
        with patch.dict("os.environ", {"GERRIT_PASSWORD": "x"}, clear=True):
            with pytest.raises(ToolError, match="CREDENTIALS_REQUIRED:"):
                await gerrit_get_change("123")

    async def test_missing_password(self):
        with patch.dict("os.environ", {"GERRIT_USERNAME": "x"}, clear=True):
            with pytest.raises(ToolError, match="CREDENTIALS_REQUIRED:"):
                await gerrit_get_change("123")


# ---------------------------------------------------------------------------
# args as JSON string
# ---------------------------------------------------------------------------


class TestArgsAsString:
    # NOTE: JSON string args parsing is not implemented yet
    pass


# ---------------------------------------------------------------------------
# list_changes
# ---------------------------------------------------------------------------


class TestListChanges:
    async def test_returns_list(self, mock_client):
        mock_client.get.return_value = _resp([_CHANGE])
        result = await gerrit_list_changes("status:open", limit=10)
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["change_number"] == 448402
        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args
        assert call_kwargs[1]["params"]["q"] == "status:open"
        assert call_kwargs[1]["params"]["n"] == 10

    async def test_default_query(self, mock_client):
        mock_client.get.return_value = _resp([])
        await gerrit_list_changes()
        params = mock_client.get.call_args[1]["params"]
        assert params["q"] == "status:open"


# ---------------------------------------------------------------------------
# get_change
# ---------------------------------------------------------------------------


class TestGetChange:
    async def test_returns_change_dict(self, mock_client):
        mock_client.get.return_value = _resp(_CHANGE)
        result = await gerrit_get_change("448402")
        data = json.loads(result)
        assert data["change_number"] == 448402
        assert data["project"] == "platform/kernel"
        assert data["status"] == "NEW"
        assert data["commit"]["subject"] == "Fix null deref in foo"
        assert data["labels"]["Code-Review"]["approved_by"] == "Bob"

    async def test_missing_change_id(self, mock_client):
        with pytest.raises(ToolError, match="missing required arg 'change_id'"):
            await gerrit_get_change(None)


# ---------------------------------------------------------------------------
# get_change_detail
# ---------------------------------------------------------------------------


class TestGetChangeDetail:
    async def test_includes_files(self, mock_client):
        files_data = {
            "/COMMIT_MSG": {},
            "drivers/foo/bar.c": {"lines_inserted": 5, "lines_deleted": 1, "size_delta": 40},
        }
        mock_client.get.side_effect = [_resp(_CHANGE), _resp(files_data)]
        result = await gerrit_get_change_detail("448402")
        data = json.loads(result)
        assert "files" in data
        assert "drivers/foo/bar.c" in data["files"]
        assert data["files"]["drivers/foo/bar.c"]["lines_inserted"] == 5


# ---------------------------------------------------------------------------
# get_change_messages
# ---------------------------------------------------------------------------


class TestGetChangeMessages:
    async def test_returns_messages(self, mock_client):
        mock_client.get.return_value = _resp(
            [
                {
                    "id": "m1",
                    "author": {"name": "Carol"},
                    "date": "2024-01-01 10:00:00.000000000",
                    "message": "Patch Set 1: looks good",
                    "_revision_number": 1,
                }
            ]
        )
        result = await gerrit_get_change_messages("448402")
        data = json.loads(result)
        assert data[0]["id"] == "m1"
        assert data[0]["author"] == "Carol"
        assert data[0]["patch_set"] == 1


class TestGetFileContent:
    async def test_decodes_base64(self, mock_client):
        encoded = base64.b64encode(b"int main() { return 0; }\n")
        mock_client.get.return_value = _plain_resp(encoded)
        result = await gerrit_get_file_content("448402", "main.c")
        data = json.loads(result)
        assert data["file_path"] == "main.c"
        assert "int main" in data["content"]


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------


class TestListProjects:
    async def test_returns_projects(self, mock_client):
        mock_client.get.return_value = _resp(
            {
                "platform/kernel": {"state": "ACTIVE", "id": "platform%2Fkernel"},
                "platform/uboot": {"state": "ACTIVE", "id": "platform%2Fuboot"},
            }
        )
        result = await gerrit_list_projects(prefix="platform")
        data = json.loads(result)
        names = [p["name"] for p in data]
        assert "platform/kernel" in names

    async def test_prefix_passed_as_param(self, mock_client):
        mock_client.get.return_value = _resp({})
        await gerrit_list_projects(prefix="kernel", limit=50)
        params = mock_client.get.call_args[1]["params"]
        assert params["p"] == "kernel"
        assert params["n"] == 50


# ---------------------------------------------------------------------------
# get_project_branches
# ---------------------------------------------------------------------------


class TestGetProjectBranches:
    async def test_returns_branches(self, mock_client):
        mock_client.get.return_value = _resp(
            [
                {"ref": "refs/heads/main", "revision": "abc123", "can_delete": False},
                {"ref": "refs/heads/stable-5.15", "revision": "def456", "can_delete": True},
            ]
        )
        result = await gerrit_get_project_branches("platform/kernel")
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["ref"] == "refs/heads/main"


# ---------------------------------------------------------------------------
# HTTP error handling
# ---------------------------------------------------------------------------


class TestHttpErrors:
    async def test_http_error_raises_tool_error(self, mock_client):
        request = httpx.Request("GET", "https://gerrit.example.com/a/changes/bad")
        mock_client.get.return_value = httpx.Response(
            404,
            content=b"Not Found",
            request=request,
        )
        with pytest.raises(ToolError, match="Gerrit HTTP 404"):
            await gerrit_get_change("bad")
