"""OpenGrok tools.

Auth is read from environment variables (or .env file):
  OPENGROK_SERVER — OpenGrok instance URL (e.g., https://opengrok.example.com)
"""

import json
import re
from typing import Any
from urllib.parse import quote

import httpx
from aiyo.tools import tool
from aiyo.tools.exceptions import ToolError

from ext.config import ExtSettings


async def health() -> dict[str, Any]:
    """Check OpenGrok connection health.

    Returns:
        Dict with keys: name, status, message
        status: "ok" | "error" | "not_configured"
    """
    cfg = ExtSettings()
    if not cfg.opengrok_server:
        return {
            "name": "opengrok",
            "status": "not_configured",
            "message": "OPENGROK_SERVER missing",
        }

    try:
        server = cfg.opengrok_server.rstrip("/")
        async with httpx.AsyncClient(follow_redirects=True, timeout=5) as client:
            resp = await client.head(server)
            resp.raise_for_status()
        return {"name": "opengrok", "status": "ok", "message": server}
    except Exception as e:
        return {"name": "opengrok", "status": "error", "message": str(e)}


def _fmt(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _server() -> str:
    cfg = ExtSettings()
    if not cfg.opengrok_server:
        raise ToolError(
            "CREDENTIALS_REQUIRED: OpenGrok server is not configured.\n\n"
            "Stop here. Do not search for alternatives or retry.\n"
            "Tell the user to add the following to ~/.aiyo/.env and restart:\n\n"
            "  OPENGROK_SERVER=https://your-opengrok.example.com\n"
        )
    return cfg.opengrok_server.rstrip("/")


def _strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return re.sub(r"\s+", " ", text).strip()


def _extract_project_from_path(path: str) -> str | None:
    parts = path.strip("/").split("/", 1)
    return parts[0] if parts and parts[0] else None


def _extract_projects_from_homepage(html_text: str) -> list[str]:
    match = re.search(
        r'<select[^>]*id="project"[^>]*>(?P<body>.*?)</select>',
        html_text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    body = match.group("body")
    projects = re.findall(r'<option[^>]*value="([^"]+)"', body, re.IGNORECASE)
    return sorted(dict.fromkeys(projects))


def _build_download_url(server: str, file_path: str, project: str | None = None) -> str:
    normalized = file_path.strip()
    if not normalized:
        raise ToolError("missing required arg 'file_path'.")
    if normalized.startswith("/"):
        download_path = normalized.lstrip("/")
    elif project:
        download_path = f"{project}/{normalized.lstrip('/')}"
    else:
        raise ToolError(
            "file_path must include the project prefix like '/project/path/to/file' "
            "or provide the 'project' arg."
        )
    return f"{server}/download/{quote(download_path, safe='/')}"


def _parse_search_html(html_text: str, search_type: str, max_results: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    current_dir = ""

    row_re = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
    dir_re = re.compile(
        r'<tr\b[^>]*class="[^"]*\bdir\b[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>.*?</tr>',
        re.IGNORECASE | re.DOTALL,
    )
    file_td_re = re.compile(r'<td[^>]*class="f"[^>]*>(.*?)</td>', re.IGNORECASE | re.DOTALL)
    code_td_re = re.compile(r"<td[^>]*><code[^>]*>(.*?)</code></td>", re.IGNORECASE | re.DOTALL)
    file_link_re = re.compile(r"<a[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
    snippet_re = re.compile(
        r'<a[^>]*class="s"[^>]*href="[^"#]*#(?P<line>\d+)"[^>]*>(?P<body>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )

    for row_match in row_re.finditer(html_text):
        row_html = row_match.group(0)
        dir_match = dir_re.search(row_html)
        if dir_match:
            current_dir = _strip_tags(dir_match.group(1))
            continue

        file_td_match = file_td_re.search(row_html)
        if not file_td_match or not current_dir:
            continue

        file_link_match = file_link_re.search(file_td_match.group(1))
        if not file_link_match:
            continue

        filename = _strip_tags(file_link_match.group(1))
        if not filename:
            continue

        path = f"{current_dir.rstrip('/')}/{filename}"
        project = _extract_project_from_path(path)

        if search_type == "path":
            results.append({"project": project, "path": path})
            if len(results) >= max_results:
                break
            continue

        code_td_match = code_td_re.search(row_html)
        snippets = snippet_re.findall(code_td_match.group(1) if code_td_match else "")
        if snippets:
            for line_number, snippet_html in snippets:
                results.append(
                    {
                        "project": project,
                        "path": path,
                        "line_number": int(line_number),
                        "line": _strip_tags(snippet_html),
                    }
                )
                if len(results) >= max_results:
                    break
        else:
            results.append({"project": project, "path": path})

        if len(results) >= max_results:
            break

    return results[:max_results]


async def _list_projects(client: httpx.AsyncClient, server: str) -> list[str]:
    try:
        resp = await client.get(f"{server}/api/v1/projects")
        resp.raise_for_status()
        projects = resp.json()
        if isinstance(projects, dict):
            return sorted(str(project) for project in projects)
        if isinstance(projects, list):
            return sorted(str(project) for project in projects)
    except Exception:
        pass

    resp = await client.get(f"{server}/")
    resp.raise_for_status()
    return _extract_projects_from_homepage(resp.text)


async def _read_file_html(
    client: httpx.AsyncClient, server: str, file_path: str, project: str | None = None
) -> str:
    url = _build_download_url(server, file_path, project)
    resp = await client.get(url)
    resp.raise_for_status()
    return _fmt({"file_path": file_path, "content": resp.text})


def _field_summary(*names: str):
    def summary(tool_args: dict[str, Any]) -> str:
        return " ".join(str(tool_args.get(name)) for name in names if tool_args.get(name))

    return summary


@tool(gatherable=True, health_check=health)
async def opengrok_list_projects() -> str:
    """List indexed OpenGrok projects."""
    server = _server()
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            return _fmt(await _list_projects(client, server))
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(f"OpenGrok list_projects failed: {exc}") from exc


@tool(gatherable=True, summary=_field_summary("query"), health_check=health)
async def opengrok_search_code(
    query: str,
    projects: list[str] | str | None = None,
    max_results: int = 100,
) -> str:
    """Full-text search across indexed source code."""
    return await _search_tool("full", query, projects, max_results)


@tool(gatherable=True, summary=_field_summary("query"), health_check=health)
async def opengrok_search_definition(
    query: str,
    projects: list[str] | str | None = None,
    max_results: int = 100,
) -> str:
    """Search definitions of functions, classes, methods, macros, etc."""
    return await _search_tool("defs", query, projects, max_results)


@tool(gatherable=True, summary=_field_summary("query"), health_check=health)
async def opengrok_search_symbol(
    query: str,
    projects: list[str] | str | None = None,
    max_results: int = 100,
) -> str:
    """Search symbol references/usages."""
    return await _search_tool("refs", query, projects, max_results)


@tool(gatherable=True, summary=_field_summary("query"), health_check=health)
async def opengrok_search_path(
    query: str,
    projects: list[str] | str | None = None,
    max_results: int = 100,
) -> str:
    """Search files or directories by path."""
    return await _search_tool("path", query, projects, max_results)


@tool(gatherable=True, summary=_field_summary("file_path", "project"), health_check=health)
async def opengrok_read_file(file_path: str, project: str | None = None) -> str:
    """Read one source file from the OpenGrok index."""
    server = _server()
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            return await _read_file(client, server, file_path, project)
    except httpx.HTTPStatusError as e:
        raise ToolError(f"OpenGrok HTTP {e.response.status_code}: {e.response.text[:500]}") from e
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e)) from e


async def _search_tool(
    search_type: str,
    query: str,
    projects: list[str] | str | None,
    max_results: int,
) -> str:
    server = _server()
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            return await _search(client, server, search_type, query, projects, max_results)
    except httpx.HTTPStatusError as e:
        raise ToolError(f"OpenGrok HTTP {e.response.status_code}: {e.response.text[:500]}") from e
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e)) from e


async def _search(
    client: httpx.AsyncClient,
    server: str,
    search_type: str,
    query: str,
    projects: list[str] | str | None,
    max_results: int,
) -> str:
    """Run an OpenGrok search API call. search_type: full | defs | refs | path."""
    query = _normalize_query(query)
    if not query:
        raise ToolError("missing required arg 'query'.")
    project_list = _normalize_projects(projects) or await _list_projects(client, server)

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    targets: list[str | None] = project_list or [None]

    for project in targets:
        remaining = max_results - len(results)
        if remaining <= 0:
            break
        try:
            hits = await _search_api_results(client, server, search_type, query, remaining, project)
        except Exception as api_exc:
            try:
                hits = await _search_html_results(
                    client, server, search_type, query, remaining, project
                )
            except Exception as html_exc:
                label = project or "*"
                errors.append(f"{label}: API {api_exc}; HTML {html_exc}")
                continue
        results.extend(hits)

    if search_type == "path":
        path_results = [{"project": r.get("project"), "path": r.get("path")} for r in results]
        if path_results:
            return _fmt(path_results[:max_results])
    elif results:
        return _fmt(results[:max_results])

    if errors:
        raise ToolError("OpenGrok search failed for all projects: " + "; ".join(errors[:5]))
    return _fmt([])


async def _read_file(
    client: httpx.AsyncClient,
    server: str,
    file_path: str,
    project: str | None = None,
) -> str:
    if not file_path:
        raise ToolError("missing required arg 'file_path'.")
    try:
        params: dict[str, str] = {}
        if project:
            params["project"] = project
        resp = await client.get(
            f"{server}/api/v1/file/content",
            params={"path": file_path, **params},
        )
        resp.raise_for_status()
        return _fmt({"file_path": file_path, "content": resp.text})
    except Exception:
        return await _read_file_html(client, server, file_path, project)


async def _search_api_results(
    client: httpx.AsyncClient,
    server: str,
    search_type: str,
    query: str,
    max_results: int,
    project: str | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {search_type: query, "maxresults": max_results}
    if project:
        params["projects"] = project

    resp = await client.get(f"{server}/api/v1/search", params=params)
    resp.raise_for_status()
    data = resp.json()

    results: list[dict[str, Any]] = []
    raw_results = data.get("results", {})
    if isinstance(raw_results, dict):
        for project_name, hits in raw_results.items():
            if not isinstance(hits, list):
                continue
            for hit in hits:
                entry: dict[str, Any] = {"project": project_name}
                if "path" in hit:
                    entry["path"] = hit["path"]
                if "lineno" in hit:
                    entry["line_number"] = hit["lineno"]
                if "line" in hit:
                    entry["line"] = hit["line"]
                results.append(entry)
    elif isinstance(raw_results, list):
        results = raw_results
    return results[:max_results]


async def _search_html_results(
    client: httpx.AsyncClient,
    server: str,
    search_type: str,
    query: str,
    max_results: int,
    project: str | None,
) -> list[dict[str, Any]]:
    params: list[tuple[str, str | int]] = [(search_type, query), ("n", max_results)]
    if project:
        params.append(("project", project))

    resp = await client.get(f"{server}/search", params=params)
    resp.raise_for_status()
    return _parse_search_html(resp.text, search_type, max_results)


def _normalize_query(query: str | None) -> str:
    return str(query).strip() if query is not None else ""


def _normalize_projects(projects: list[str] | str | None) -> list[str]:
    if isinstance(projects, str):
        return [projects]
    if isinstance(projects, list):
        return [str(project) for project in projects if str(project).strip()]
    return []
