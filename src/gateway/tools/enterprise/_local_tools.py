"""Local enterprise tool helpers.

These helpers provide deterministic, repo-backed fallbacks for enterprise MCP
tools when external connectors or services are not configured.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.types import TextContent

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DOC_ROOT = PROJECT_ROOT / "docs"
CODE_ROOTS = [PROJECT_ROOT / "src", PROJECT_ROOT / "tests", PROJECT_ROOT / "frontend"]

_TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".yml", ".yaml", ".sql", ".txt", ".toml",
}
_LANGUAGE_SUFFIXES = {
    "python": {".py"},
    "typescript": {".ts", ".tsx"},
    "javascript": {".js", ".jsx"},
    "json": {".json"},
    "markdown": {".md"},
    "yaml": {".yml", ".yaml"},
}


def json_text_response(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, default=_json_default))]


def search_workspace(
    query: str,
    *,
    roots: list[Path],
    suffixes: set[str] | None = None,
    limit: int = 10,
    path_filter: str | None = None,
) -> list[dict[str, Any]]:
    phrase = query.strip().lower()
    tokens = [token for token in re.findall(r"[a-zA-Z0-9_./:-]+", phrase) if len(token) > 1]
    results: list[dict[str, Any]] = []

    for file_path in _iter_files(roots, suffixes=suffixes, path_filter=path_filter):
        text = _read_text(file_path)
        if not text:
            continue

        score, line_no = _score_text(text, phrase, tokens)
        if score <= 0 or line_no is None:
            continue

        lines = text.splitlines()
        start = max(0, line_no - 3)
        end = min(len(lines), line_no + 2)
        snippet = "\n".join(lines[start:end]).strip()
        results.append(
            {
                "path": str(file_path.relative_to(PROJECT_ROOT)),
                "title": _file_title(file_path, text),
                "line": line_no + 1,
                "snippet": snippet,
                "score": round(score, 3),
                "last_modified": datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC).isoformat(),
            }
        )

    results.sort(key=lambda item: (-item["score"], item["path"]))
    return results[:limit]


def explain_code_file(
    file_path: str,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    resolved = resolve_workspace_path(file_path)
    text = _read_text(resolved)
    lines = text.splitlines()
    start_idx = max((start_line or 1) - 1, 0)
    end_idx = min(end_line or len(lines), len(lines))
    excerpt = "\n".join(lines[start_idx:end_idx])
    symbols = re.findall(r"^(?:class|def|async def)\s+([A-Za-z0-9_]+)", text, flags=re.MULTILINE)

    return {
        "file": str(resolved.relative_to(PROJECT_ROOT)),
        "language": resolved.suffix.lstrip(".") or "text",
        "lines": f"{start_idx + 1}-{end_idx}",
        "line_count": len(lines),
        "symbols": symbols[:20],
        "imports": re.findall(r"^(?:from|import)\s+([^\n]+)", text, flags=re.MULTILINE)[:20],
        "excerpt": excerpt,
        "summary": _summarize_text(excerpt or text, max_words=120),
    }


def summarize_document_path(document_id: str, max_words: int) -> dict[str, Any]:
    resolved = resolve_workspace_path(document_id, roots=[DOC_ROOT, PROJECT_ROOT])
    text = _read_text(resolved)
    headings = [line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")]
    summary = _summarize_text(text, max_words=max_words)
    return {
        "document_id": str(resolved.relative_to(PROJECT_ROOT)),
        "title": headings[0] if headings else resolved.stem,
        "summary": summary,
        "key_points": headings[1:6] if len(headings) > 1 else [],
        "word_count": len(summary.split()),
    }


def service_graph() -> dict[str, dict[str, Any]]:
    compose = PROJECT_ROOT / "docker-compose.yml"
    lines = compose.read_text(encoding="utf-8").splitlines()
    graph: dict[str, dict[str, Any]] = {}
    in_services = False
    current: str | None = None
    in_depends = False
    in_ports = False

    for raw_line in lines:
        if raw_line.startswith("services:"):
            in_services = True
            continue
        if in_services and raw_line and not raw_line.startswith(" "):
            break

        service_match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", raw_line)
        if service_match:
            current = service_match.group(1)
            graph.setdefault(current, {"depends_on": [], "ports": []})
            in_depends = False
            in_ports = False
            continue

        if current is None:
            continue

        if re.match(r"^    depends_on:\s*$", raw_line):
            in_depends = True
            in_ports = False
            continue
        if re.match(r"^    ports:\s*$", raw_line):
            in_ports = True
            in_depends = False
            continue
        if re.match(r"^    [A-Za-z0-9_-]+:", raw_line):
            in_depends = False
            in_ports = False

        if in_depends:
            dep_match = re.match(r"^      ([A-Za-z0-9_-]+):\s*$", raw_line)
            if dep_match:
                graph[current]["depends_on"].append(dep_match.group(1))
                continue
        if in_ports:
            port_match = re.match(r'^      - "(\d+):(\d+)"', raw_line)
            if port_match:
                graph[current]["ports"].append(
                    {"host": int(port_match.group(1)), "container": int(port_match.group(2))}
                )

    return graph


def git_history(limit: int, *, grep: str | None = None, paths: list[str] | None = None) -> list[dict[str, str]]:
    args = [
        "git",
        "--no-pager",
        "log",
        f"-n{limit}",
        "--date=iso",
        "--pretty=format:%H%x1f%ad%x1f%an%x1f%s",
    ]
    if grep:
        args.extend(["--grep", grep])
    if paths:
        args.append("--")
        args.extend(paths)

    try:
        proc = subprocess.run(
            args,
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []

    if proc.returncode != 0:
        return []

    rows: list[dict[str, str]] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        rows.append(
            {
                "commit": parts[0],
                "timestamp": parts[1],
                "author": parts[2],
                "message": parts[3],
            }
        )
    return rows


def latest_file_authors(resource: str, limit: int = 5) -> list[dict[str, str]]:
    matches = search_workspace(resource, roots=[PROJECT_ROOT], suffixes=_TEXT_SUFFIXES, limit=limit)
    owners: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in matches:
        history = git_history(1, paths=[match["path"]])
        if not history:
            continue
        commit = history[0]
        key = f"{commit['author']}:{match['path']}"
        if key in seen:
            continue
        seen.add(key)
        owners.append(
            {
                "owner": commit["author"],
                "path": match["path"],
                "last_commit": commit["commit"],
                "last_updated": commit["timestamp"],
            }
        )
    return owners


def service_health_snapshot(service: str | None = None) -> list[dict[str, Any]]:
    graph = service_graph()
    services = [service] if service else sorted(graph.keys())
    snapshots: list[dict[str, Any]] = []

    for name in services:
        info = graph.get(name, {"ports": [], "depends_on": []})
        ports = info.get("ports", [])
        port_status = []
        overall = "unknown"
        for port in ports:
            reachable = _is_port_open(port["host"])
            port_status.append({"host_port": port["host"], "container_port": port["container"], "reachable": reachable})
        if port_status:
            overall = "healthy" if any(item["reachable"] for item in port_status) else "unreachable"
        snapshots.append(
            {
                "service": name,
                "status": overall,
                "ports": port_status,
                "depends_on": info.get("depends_on", []),
                "timestamp": datetime.now(tz=UTC).isoformat(),
            }
        )

    return snapshots


def resolve_workspace_path(path_or_id: str, roots: list[Path] | None = None) -> Path:
    candidate = Path(path_or_id)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    roots = roots or [PROJECT_ROOT]
    for root in roots:
        direct = root / path_or_id
        if direct.exists():
            return direct
    stem = candidate.stem.lower()
    for file_path in _iter_files(roots, suffixes=_TEXT_SUFFIXES):
        if file_path.stem.lower() == stem or str(file_path.relative_to(PROJECT_ROOT)).lower() == path_or_id.lower():
            return file_path
    raise FileNotFoundError(path_or_id)


def _iter_files(
    roots: list[Path],
    *,
    suffixes: set[str] | None,
    path_filter: str | None = None,
):
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        pattern = path_filter or "**/*"
        for file_path in root.glob(pattern):
            if file_path in seen or not file_path.is_file():
                continue
            seen.add(file_path)
            if suffixes is not None and file_path.suffix.lower() not in suffixes:
                continue
            if file_path.stat().st_size > 512_000:
                continue
            yield file_path


def _score_text(text: str, phrase: str, tokens: list[str]) -> tuple[float, int | None]:
    lowered = text.lower()
    score = 0.0
    first_match: int | None = None
    if phrase and phrase in lowered:
        score += 10.0
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        lowered_line = line.lower()
        line_hits = sum(1 for token in tokens if token in lowered_line)
        if phrase and phrase in lowered_line:
            line_hits += 5
        if line_hits and first_match is None:
            first_match = idx
        score += float(line_hits)
    return score, first_match


def _read_text(file_path: Path) -> str:
    try:
        return file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _file_title(file_path: Path, text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("# ").strip()
    return file_path.name


def _summarize_text(text: str, max_words: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""
    words = cleaned.split()
    return " ".join(words[:max_words])


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return str(value)


def _is_port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False
