"""Tests for web fetching tool."""

import pytest
from unittest.mock import patch, MagicMock

from aiyo.tools.web import fetch_url


class TestFetchUrl:
    """Tests for fetch_url function."""

    @patch('aiyo.tools.web.requests.get')
    def test_fetch_successful(self, mock_get):
        """Test successful URL fetching."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Hello, World!</body></html>"
        mock_get.return_value = mock_response

        result = fetch_url("https://example.com")

        assert "Hello, World!" in result
        mock_get.assert_called_once()

    @patch('aiyo.tools.web.requests.get')
    def test_fetch_with_html_extraction(self, mock_get):
        """Test HTML content extraction."""
        mock_response = MagicMock()
        mock_response.status_code = 200
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
        mock_get.return_value = mock_response

        result = fetch_url("https://example.com")

        # Should contain main content but may filter navigation/footer
        assert "Main Content" in result

    @patch('aiyo.tools.web.requests.get')
    def test_fetch_http_error(self, mock_get):
        """Test handling of HTTP errors."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = Exception("404 Client Error")
        mock_get.return_value = mock_response

        result = fetch_url("https://example.com/notfound")

        assert "Error:" in result

    @patch('aiyo.tools.web.requests.get')
    def test_fetch_network_error(self, mock_get):
        """Test handling of network errors."""
        import requests
        mock_get.side_effect = requests.RequestException("Connection failed")

        result = fetch_url("https://example.com")

        assert "Error:" in result
        assert "Connection" in result or "fetch" in result.lower()

    @patch('aiyo.tools.web.requests.get')
    def test_fetch_timeout(self, mock_get):
        """Test handling of request timeout."""
        import requests
        mock_get.side_effect = requests.Timeout("Request timed out")

        result = fetch_url("https://example.com")

        assert "Error:" in result

    @patch('aiyo.tools.web.requests.get')
    def test_fetch_invalid_url(self, mock_get):
        """Test handling of invalid URL."""
        result = fetch_url("not-a-valid-url")

        assert "Error:" in result
        mock_get.assert_not_called()

    @patch('aiyo.tools.web.requests.get')
    def test_fetch_empty_response(self, mock_get):
        """Test handling of empty response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ""
        mock_get.return_value = mock_response

        result = fetch_url("https://example.com")

        # Should handle empty content gracefully
        assert isinstance(result, str)

    @patch('aiyo.tools.web.requests.get')
    def test_fetch_large_content(self, mock_get):
        """Test handling of large content."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Large content " * 10000
        mock_get.return_value = mock_response

        result = fetch_url("https://example.com")

        # Should handle large content without crashing
        assert isinstance(result, str)
        assert len(result) > 0

    @patch('aiyo.tools.web.requests.get')
    def test_fetch_uses_headers(self, mock_get):
        """Test that proper headers are sent with request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Content"
        mock_get.return_value = mock_response

        fetch_url("https://example.com")

        # Verify headers were passed
        call_args = mock_get.call_args
        assert 'headers' in call_args[1] or 'headers' in str(call_args)
