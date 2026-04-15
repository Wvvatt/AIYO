"""Web fetch tool."""

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

from .exceptions import ToolError
from .tool_meta import tool

_MAX_REDIRECTS = 5


def _fetch_url_summary(tool_args: dict[str, object]) -> str:
    return str(tool_args.get("url", ""))


def _is_blocked_hostname(hostname: str | None) -> bool:
    if not hostname:
        return True

    host = hostname.strip().lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"}:
        return True

    try:
        ip = ipaddress.ip_address(host)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # If DNS cannot resolve, let httpx handle the request error later.
        return False

    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True

    return False


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ToolError("URL must start with http:// or https://.")
    if _is_blocked_hostname(parsed.hostname):
        raise ToolError(f"Refusing to fetch non-public host: '{parsed.hostname}'.")


@tool(gatherable=True, summary=_fetch_url_summary)
async def fetch_url(url: str) -> str:
    """Fetch a web page and return its main text content in plain text.

    Extracts the readable body text (strips HTML, navigation, ads, etc.).
    Falls back to raw response text if extraction fails.

    Args:
        url: The full URL to fetch (must start with http:// or https://).

    Raises:
        ToolError: If URL invalid, HTTP error, or network request fails.
    """
    _validate_url(url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=30) as client:
            current_url = url
            response = None
            for _ in range(_MAX_REDIRECTS + 1):
                _validate_url(current_url)
                response = await client.get(current_url, headers=headers)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ToolError(f"redirect without location header for '{current_url}'.")
                    current_url = urljoin(str(response.url), location)
                    continue
                break
            else:
                raise ToolError(f"too many redirects (>{_MAX_REDIRECTS}) for '{url}'.")

            if response is None:
                raise ToolError(f"failed to fetch '{url}'.")

        if response.status_code >= 400:
            raise ToolError(f"HTTP {response.status_code} for '{current_url}'.")
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
