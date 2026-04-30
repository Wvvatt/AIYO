"""Tests for web fetching tool."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from aiyo.tools.exceptions import ToolError
from aiyo.tools.web import fetch_url


@pytest.fixture(autouse=True)
def mock_getaddrinfo():
    """Prevent real DNS lookups in tests — example.com may resolve to reserved IPs."""
    with patch("aiyo.tools.web.socket.getaddrinfo", return_value=[]):
        yield


class TestFetchUrl:
    """Tests for fetch_url function."""

    @pytest.mark.asyncio
    @patch("aiyo.tools.web.httpx.AsyncClient")
    async def test_fetch_successful(self, mock_client_class):
        """Test successful URL fetching."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "Hello, World!"

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        result = await fetch_url("https://example.com")

        assert "Hello, World!" in result
        mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    @patch("aiyo.tools.web.httpx.AsyncClient")
    async def test_fetch_with_html_extraction(self, mock_client_class):
        """Test HTML content extraction."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.text = """
        <html>
            <head><title>Test Page</title></head>
            <body>
                <nav>Navigation</nav>
                <main>Main Content</main>
                <footer>Footer</footer>
            </body>
        </html>
        """

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        result = await fetch_url("https://example.com")

        # Should contain main content (trafilatura extraction may vary)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    @patch("aiyo.tools.web.httpx.AsyncClient")
    async def test_fetch_http_error(self, mock_client_class):
        """Test handling of HTTP errors."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        with pytest.raises(ToolError, match="HTTP 404"):
            await fetch_url("https://example.com/notfound")

    @pytest.mark.asyncio
    @patch("aiyo.tools.web.httpx.AsyncClient")
    async def test_fetch_network_error(self, mock_client_class):
        """Test handling of network errors."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.RequestError("Connection failed")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        with pytest.raises(ToolError, match="Connection"):
            await fetch_url("https://example.com")

    @pytest.mark.asyncio
    @patch("aiyo.tools.web.httpx.AsyncClient")
    async def test_fetch_timeout(self, mock_client_class):
        """Test handling of request timeout."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("Request timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        with pytest.raises(ToolError):
            await fetch_url("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_invalid_url(self):
        """Test handling of invalid URL."""
        with pytest.raises(ToolError, match="http://"):
            await fetch_url("not-a-valid-url")

    @pytest.mark.asyncio
    async def test_fetch_blocks_private_host(self):
        """Test SSRF guard blocks localhost/private targets."""
        with pytest.raises(ToolError, match="Refusing to fetch non-public host"):
            await fetch_url("http://127.0.0.1/internal")

    @pytest.mark.asyncio
    @patch("aiyo.tools.web.httpx.AsyncClient")
    async def test_fetch_empty_response(self, mock_client_class):
        """Test handling of empty response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = ""

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        result = await fetch_url("https://example.com")

        # Should handle empty content gracefully
        assert isinstance(result, str)

    @pytest.mark.asyncio
    @patch("aiyo.tools.web.httpx.AsyncClient")
    async def test_fetch_large_content(self, mock_client_class):
        """Test handling of large content."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "Large content " * 10000

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        result = await fetch_url("https://example.com")

        # Should handle large content without crashing
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    @patch("aiyo.tools.web.httpx.AsyncClient")
    async def test_fetch_uses_headers(self, mock_client_class):
        """Test that proper headers are sent with request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "Content"

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        await fetch_url("https://example.com")

        # Verify headers were passed
        call_args = mock_client.get.call_args
        assert "headers" in call_args[1]
        assert "User-Agent" in call_args[1]["headers"]

    @pytest.mark.asyncio
    @patch("aiyo.tools.web.httpx.AsyncClient")
    async def test_fetch_blocks_redirect_to_private_host(self, mock_client_class):
        """Test SSRF guard is also applied after redirect."""
        redirect_response = MagicMock()
        redirect_response.status_code = 302
        redirect_response.headers = {"location": "http://localhost/admin"}
        redirect_response.url = "https://example.com/start"

        mock_client = AsyncMock()
        mock_client.get.return_value = redirect_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        with pytest.raises(ToolError, match="Refusing to fetch non-public host"):
            await fetch_url("https://example.com/start")

        # Should stop before issuing redirected request
        mock_client.get.assert_called_once()
