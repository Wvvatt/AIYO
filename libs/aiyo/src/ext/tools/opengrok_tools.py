"""OpenGrok tool: a single CLI-style interface for all OpenGrok operations.

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


def health() -> dict[str, Any]:
    """Check OpenGrok connection health.

    Returns:
        Dict with keys: name, status, message
        status: "ok" | "error" | "not_configured"
    """
    cfg = ExtSettings()
    if not cfg.opengrok_server:
        return {
            "name": "opengrok_cli",
            "status": "not_configured",
            "message": "OPENGROK_SERVER missing",
        }

    try:
        server = cfg.opengrok_server.rstrip("/")
        with httpx.Client(follow_redirects=True, timeout=5) as client:
            resp = client.head(server)
            resp.raise_for_status()
        return {"name": "opengrok_cli", "status": "ok", "message": server}
    except Exception as e:
        return {"name": "opengrok_cli", "status": "error", "message": str(e)}


def _fmt(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


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
        raise ToolError("missing required arg 'file_path' for command 'read_file'.")
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


async def _list_projects_html(client: httpx.AsyncClient, server: str) -> str:
    resp = await client.get(f"{server}/")
    resp.raise_for_status()
    return _fmt(_extract_projects_from_homepage(resp.text))


async def _read_file_html(
    client: httpx.AsyncClient, server: str, file_path: str, project: str | None = None
) -> str:
    url = _build_download_url(server, file_path, project)
    resp = await client.get(url)
    resp.raise_for_status()
    return _fmt({"file_path": file_path, "content": resp.text})


async def _search_html(
    client: httpx.AsyncClient,
    server: str,
    search_type: str,
    args: dict[str, Any],
) -> str:
    query = args.get("query")
    if not query:
        raise ToolError("missing required arg 'query' for search command.")

    max_results = int(args.get("max_results", 100))
    projects = args.get("projects")

    params: list[tuple[str, str | int]] = [(search_type, query), ("n", max_results)]
    if isinstance(projects, list):
        params.extend(("project", project) for project in projects)

    resp = await client.get(f"{server}/search", params=params)
    resp.raise_for_status()
    return _fmt(_parse_search_html(resp.text, search_type, max_results))


def _opengrok_summary(tool_args: dict[str, Any]) -> str:
    cmd = tool_args.get("command", "")
    raw = tool_args.get("args") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    query = raw.get("query", "") if isinstance(raw, dict) else ""
    return f"{cmd} {query}".strip() if query else cmd


@tool(gatherable=True, summary=_opengrok_summary, health_check=health)
async def opengrok_cli(command: str, args: dict[str, Any] | None = None) -> str:
    """Execute an OpenGrok code search operation.

    Auth is read from env var: OPENGROK_SERVER.

    OpenGrok is a fast source code search and cross-reference engine. Use it to search
    through large indexed codebases (e.g., Android, Linux kernel, RTOS) for code,
    definitions, symbols, and file paths.

    IMPORTANT — projects: Use "list_projects" first to discover available project names.
    Projects are case-sensitive (e.g., "androidU", "automotive_S").
    IMPORTANT — navigation order:
      1. Use "search_path" to find candidate file paths when you only know a directory,
         module, or partial filename.
      2. Use "read_file" only after you have a concrete file path from search results.
      3. Never pass a directory path to "read_file". It only accepts a file path.
      4. If the user asks for "everything under X", do not use "read_file" on X.
         Use "search_path" first and then read specific files.
    IMPORTANT — avoid retry loops:
      If "read_file" fails because the target is not a file, switch to "search_path".
      Do not retry "read_file" with the same directory-like path.

    Supported commands
    ──────────────────

    "list_projects"
        List all indexed projects (code repositories) available in OpenGrok.
        Returns  : [project_name, ...]

    "search_code"
        Full-text search across indexed source code. Good for finding code snippets,
        comments, strings, log messages, etc.
        Required : query (str) — search keywords, e.g. "ActivityManager", "TODO fix"
        Optional : projects (list[str]) — limit to these projects, e.g. ["androidU", "androidT"]
                   max_results (int, default 100) — max results to return
        Returns  : [{project, path, line_number, line}]

    "search_definition"
        Search for definitions of functions, classes, methods, macros, etc.
        Good for finding where an API or type is defined.
        Required : query (str) — definition name, e.g. "ActivityManager", "onCreate"
        Optional : projects (list[str]) — limit to these projects
                   max_results (int, default 100)
        Returns  : [{project, path, line_number, line}]

    "search_symbol"
        Search for symbol references/usages. Good for finding where a function or class
        is called or referenced.
        Required : query (str) — symbol name
        Optional : projects (list[str]) — limit to these projects
                   max_results (int, default 100)
        Returns  : [{project, path, line_number, line}]

    "search_path"
        Search for files or directories by path. Use this first when you do not already
        have an exact file path.
        Required : query (str) — path keyword, e.g. "AndroidManifest.xml", "framework/base"
        Optional : projects (list[str]) — limit to these projects
                   max_results (int, default 100)
        Returns  : [{project, path}]
        Use when:
          - You only know a directory name, module name, or partial filename
          - You want to enumerate candidate files under a subtree
        Do not use when:
          - You already have the full path to a file and want its content
        Example:
          command="search_path", args={"query": "multimedia", "projects": ["rdk7"]}

    "read_file"
        Read the content of one source file from the OpenGrok index.
        Required : file_path (str) — exact file path, not a directory,
                   e.g. "/automotive_S/rtos/lib/parking-core/pipeline/ui.c"
        Optional : project (str) — project name, only if file_path does not already
                   include the project prefix
        Returns  : {file_path, content}
        Use when:
          - You already have one concrete file path from "search_path", "search_code",
            "search_definition", or "search_symbol"
        Do not use when:
          - The path is a directory like "/rdk7/multimedia"
          - You want to list files in a directory
          - You want multiple files at once
        Correct examples:
          command="read_file", args={"file_path": "/rdk7/aml-comp/multimedia/libvideorender/Makefile"}
          command="read_file", args={"project": "rdk7", "file_path": "aml-comp/multimedia/libvideorender/Makefile"}
        Incorrect example:
          command="read_file", args={"file_path": "/rdk7/aml-comp/multimedia"}

    Args:
        command: The operation to perform (see list above).
        args: Parameters for the operation as a dict.
    """
    if args is None:
        args = {}

    cfg = ExtSettings()
    if not cfg.opengrok_server:
        raise ToolError(
            "CREDENTIALS_REQUIRED: OpenGrok server is not configured.\n\n"
            "Stop here. Do not search for alternatives or retry.\n"
            "Tell the user to add the following to ~/.aiyo/.env and restart:\n\n"
            "  OPENGROK_SERVER=https://your-opengrok.example.com\n"
        )

    server = cfg.opengrok_server.rstrip("/")

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            if command == "list_projects":
                try:
                    resp = await client.get(f"{server}/api/v1/projects")
                    resp.raise_for_status()
                    projects = resp.json()
                    if isinstance(projects, dict):
                        return _fmt(sorted(projects.keys()))
                    return _fmt(sorted(projects) if isinstance(projects, list) else projects)
                except Exception:
                    return await _list_projects_html(client, server)

            elif command == "search_code":
                return await _search(client, server, "full", args)

            elif command == "search_definition":
                return await _search(client, server, "defs", args)

            elif command == "search_symbol":
                return await _search(client, server, "refs", args)

            elif command == "search_path":
                return await _search(client, server, "path", args)

            elif command == "read_file":
                file_path = args.get("file_path")
                if not file_path:
                    raise ToolError("missing required arg 'file_path' for command 'read_file'.")
                project = args.get("project")
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

            else:
                raise ToolError(
                    f"Unknown command '{command}'. "
                    "Valid commands: list_projects, search_code, search_definition, "
                    "search_symbol, search_path, read_file."
                )

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
    args: dict[str, Any],
) -> str:
    """Run an OpenGrok search API call.

    search_type: "full" | "defs" | "refs" | "path"
    """
    query = args.get("query")
    if not query:
        raise ToolError("missing required arg 'query' for search command.")
    max_results = int(args.get("max_results", 100))
    projects = args.get("projects")

    params: dict[str, Any] = {search_type: query, "maxresults": max_results}
    if projects and isinstance(projects, list):
        params["projects"] = ",".join(projects)

    try:
        resp = await client.get(f"{server}/api/v1/search", params=params)
        resp.raise_for_status()
        data = resp.json()

        # OpenGrok search API returns {"resultCount": N, "results": {project: [{path, lineno, line}]}}
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

        if search_type == "path":
            return _fmt([{"project": r.get("project"), "path": r.get("path")} for r in results])
        return _fmt(results[:max_results])
    except Exception:
        return await _search_html(client, server, search_type, args)
