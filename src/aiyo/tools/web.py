"""Web fetch tool."""

import re

import httpx

from .exceptions import ToolError


async def fetch_url(url: str) -> str:
    """Fetch a web page and return its main text content in plain text.

    Extracts the readable body text (strips HTML, navigation, ads, etc.).
    Falls back to raw response text if extraction fails.

    Args:
        url: The full URL to fetch (must start with http:// or https://).

    Raises:
        ToolError: If URL invalid, HTTP error, or network request fails.
    """
    if not url.startswith(("http://", "https://")):
        raise ToolError("URL must start with http:// or https://.")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(url, headers=headers)
        if response.status_code >= 400:
            raise ToolError(f"HTTP {response.status_code} for '{url}'.")
    except httpx.RequestError as e:
        raise ToolError(f"fetching '{url}': {e}") from e

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        text = response.text[:20_000]
        if len(response.text) > 20_000:
            text += "\n[truncated]"
        return text

    try:
        import trafilatura

        extracted = trafilatura.extract(response.text, include_comments=False)
        if extracted:
            return extracted
    except Exception:
        pass

    text = re.sub(r"<[^>]+>", " ", response.text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:20_000] + ("\n[truncated]" if len(text) > 20_000 else "")
