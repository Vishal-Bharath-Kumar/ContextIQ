"""Local enterprise tool helpers.

These helpers provide deterministic, repo-backed fallbacks for enterprise MCP
tools when external connectors or services are not configured.
"""

from __future__ import annotations

from collections import Counter
import json
import os
import re
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.types import TextContent

PROJECT_ROOT = Path(__file__).resolve().parents[4]
WORKSPACE_ROOT = Path(os.environ.get("CONTEXTIQ_ENTERPRISE_WORKSPACE_ROOT", str(PROJECT_ROOT))).expanduser()
DOC_ROOT = Path(os.environ.get("CONTEXTIQ_ENTERPRISE_DOC_ROOT", str(WORKSPACE_ROOT / "docs"))).expanduser()
_CODE_ROOTS_ENV = os.environ.get("CONTEXTIQ_ENTERPRISE_CODE_ROOTS")
if _CODE_ROOTS_ENV:
    CODE_ROOTS = [Path(part.strip()).expanduser() for part in _CODE_ROOTS_ENV.split(",") if part.strip()]
else:
    CODE_ROOTS = [WORKSPACE_ROOT / "src", WORKSPACE_ROOT / "tests", WORKSPACE_ROOT / "frontend"]

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
    sanitised_payload, masking_counts = sanitize_payload(payload)
    governance = sanitised_payload.setdefault("governance", {})
    existing_counts = governance.get("masking_counts") or {}
    governance["masking_counts"] = _merge_count_maps(existing_counts, masking_counts)
    governance["redacted"] = bool(governance.get("redacted") or sum(masking_counts.values()) > 0)
    return [TextContent(type="text", text=json.dumps(sanitised_payload, default=_json_default))]


def build_tool_response(
    *,
    status: str,
    summary: str,
    data: dict[str, Any] | list[Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
    governance: dict[str, Any] | None = None,
    routing: dict[str, Any] | None = None,
    compression: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "summary": summary,
        "data": data,
        "diagnostics": diagnostics or {},
        "governance": governance or {},
        "routing": routing or {},
        "compression": compression or {},
    }


def build_error_response(
    *,
    summary: str,
    error: Exception,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = build_tool_response(
        status="error",
        summary=summary,
        data=None,
        diagnostics={
            **(diagnostics or {}),
            "error_type": type(error).__name__,
            "error_message": str(error),
        },
        governance={"blocked": False, "redacted": False},
    )
    return payload


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

        relative_path = _display_path(file_path)
        title = _file_title(file_path, text)
        score, line_no, matched_terms = _score_text(
            text,
            phrase,
            tokens,
            path_text=relative_path.lower(),
            title_text=title.lower(),
        )
        if score <= 0 or line_no is None:
            continue

        lines = text.splitlines()
        start = max(0, line_no - 3)
        end = min(len(lines), line_no + 2)
        snippet = "\n".join(lines[start:end]).strip()
        results.append(
            {
                "path": relative_path,
                "title": title,
                "line": line_no + 1,
                "snippet": snippet,
                "score": round(score, 3),
                "matched_terms": matched_terms,
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
        "file": _display_path(resolved),
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
        "document_id": _display_path(resolved),
        "title": headings[0] if headings else resolved.stem,
        "summary": summary,
        "key_points": headings[1:6] if len(headings) > 1 else [],
        "word_count": len(summary.split()),
    }


def service_graph() -> dict[str, dict[str, Any]]:
    compose = resolve_compose_path()
    if compose is None:
        return {}
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


def service_graph_diagnostics() -> dict[str, Any]:
    compose = resolve_compose_path()
    if compose is None:
        return {
            "adapter": "docker_compose",
            "source_available": False,
            "compose_path": None,
            "degraded_reasons": [
                "No docker-compose metadata was available in the runtime environment.",
            ],
        }

    return {
        "adapter": "docker_compose",
        "source_available": True,
        "compose_path": str(compose),
        "degraded_reasons": [],
    }


def resolve_compose_path() -> Path | None:
    candidate_strings = [
        os.environ.get("CONTEXTIQ_COMPOSE_PATH"),
        os.environ.get("CONTEXTIQ_LOCAL_COMPOSE_PATH"),
        str(WORKSPACE_ROOT / "docker-compose.yml"),
        str(PROJECT_ROOT / "docker-compose.yml"),
        str(Path.cwd() / "docker-compose.yml"),
    ]
    candidate_strings.extend(str(parent / "docker-compose.yml") for parent in WORKSPACE_ROOT.parents)
    candidate_strings.extend(str(parent / "docker-compose.yml") for parent in PROJECT_ROOT.parents)

    seen: set[Path] = set()
    for candidate_string in candidate_strings:
        if not candidate_string:
            continue
        candidate = Path(candidate_string).expanduser()
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def workspace_coverage(
    *,
    roots: list[Path],
    suffixes: set[str] | None = None,
    path_filter: str | None = None,
) -> dict[str, Any]:
    scanned_files = 0
    root_summaries: list[dict[str, Any]] = []
    for root in roots:
        exists = root.exists()
        root_count = 0
        if exists:
            for _file_path in _iter_files([root], suffixes=suffixes, path_filter=path_filter):
                root_count += 1
        scanned_files += root_count
        root_summaries.append(
            {
                "root": _display_root(root),
                "available": exists,
                "scanned_files": root_count,
            }
        )

    return {
        "mode": "workspace_scan",
        "index_required": False,
        "index_ready": True,
        "index_freshness": "live_filesystem",
        "scanned_files": scanned_files,
        "roots": root_summaries,
        "path_filter": path_filter,
        "suffixes": sorted(suffixes) if suffixes is not None else None,
    }


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


def compose_service_logs(
    *,
    query: str,
    service: str | None = None,
    level: str | None = None,
    limit: int = 50,
) -> list[dict[str, str]]:
    compose = resolve_compose_path()
    if compose is None:
        return []

    args = [
        "docker",
        "compose",
        "-f",
        str(compose),
        "logs",
        "--no-color",
        "--timestamps",
        f"--tail={max(limit * 4, limit)}",
    ]
    if service:
        args.append(service)

    try:
        proc = subprocess.run(
            args,
            cwd=compose.parent,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []

    if proc.returncode != 0:
        return []

    lowered_query = query.lower().strip()
    lowered_level = level.lower().strip() if level else None
    rows: list[dict[str, str]] = []
    for raw_line in proc.stdout.splitlines():
        parsed = _parse_compose_log_line(raw_line)
        if parsed is None:
            continue
        message = parsed["message"]
        message_lower = message.lower()
        if lowered_query and lowered_query not in message_lower:
            continue
        if lowered_level and lowered_level not in message_lower:
            continue
        rows.append(parsed)
        if len(rows) >= limit:
            break
    return rows


def _parse_compose_log_line(raw_line: str) -> dict[str, str] | None:
    parts = raw_line.split("|", 1)
    if len(parts) != 2:
        return None
    service_part = parts[0].strip()
    message_part = parts[1].strip()
    if not message_part:
        return None

    timestamp = ""
    message = message_part
    message_tokens = message_part.split(" ", 1)
    if len(message_tokens) == 2 and "T" in message_tokens[0]:
        timestamp, message = message_tokens[0], message_tokens[1]

    service_name = service_part.split()[0] if service_part else "unknown"
    level = _infer_log_level(message)
    return {
        "timestamp": timestamp,
        "service": service_name,
        "level": level,
        "message": message.strip(),
    }


def _infer_log_level(message: str) -> str:
    lowered = message.lower()
    for candidate in ("critical", "error", "warn", "warning", "info", "debug"):
        if candidate in lowered:
            return "WARN" if candidate == "warning" else candidate.upper()
    return "INFO"


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
    roots = roots or [WORKSPACE_ROOT, PROJECT_ROOT]
    for root in roots:
        direct = root / path_or_id
        if direct.exists():
            return direct
    stem = candidate.stem.lower()
    for file_path in _iter_files(roots, suffixes=_TEXT_SUFFIXES):
        relative_path = _display_path(file_path).lower()
        if file_path.stem.lower() == stem or relative_path == path_or_id.lower():
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


def sanitize_payload(value: Any) -> tuple[Any, dict[str, int]]:
    if isinstance(value, str):
        return _mask_sensitive_string(value)
    if isinstance(value, list):
        items: list[Any] = []
        counts: Counter[str] = Counter()
        for item in value:
            sanitised, item_counts = sanitize_payload(item)
            items.append(sanitised)
            counts.update(item_counts)
        return items, dict(counts)
    if isinstance(value, dict):
        mapping: dict[str, Any] = {}
        counts = Counter()
        for key, item in value.items():
            sanitised, item_counts = sanitize_payload(item)
            mapping[key] = sanitised
            counts.update(item_counts)
        return mapping, dict(counts)
    return value, {}


def _score_text(
    text: str,
    phrase: str,
    tokens: list[str],
    *,
    path_text: str,
    title_text: str,
) -> tuple[float, int | None, list[str]]:
    lowered = text.lower()
    score = 0.0
    best_line_idx: int | None = None
    best_line_score = 0.0
    matched_terms = sorted({token for token in tokens if token in lowered or token in path_text or token in title_text})
    if phrase and phrase in lowered:
        score += 10.0
    if phrase and phrase in path_text:
        score += 8.0
    if phrase and phrase in title_text:
        score += 6.0
    score += sum(1.5 for token in tokens if token in path_text)
    score += sum(1.0 for token in tokens if token in title_text)
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        lowered_line = line.lower()
        line_hits = float(sum(1 for token in tokens if token in lowered_line))
        if phrase and phrase in lowered_line:
            line_hits += 5
        if line_hits > best_line_score:
            best_line_score = line_hits
            best_line_idx = idx
        score += float(line_hits)
    return score, best_line_idx, matched_terms


def _mask_sensitive_string(value: str) -> tuple[str, dict[str, int]]:
    try:
        from src.governance.detection.pattern_registry import PatternRegistry  # noqa: PLC0415
    except Exception:
        return value, {}

    findings = PatternRegistry().scan_text(value, "payload")
    if not findings:
        return value, {}

    counts: Counter[str] = Counter()
    result = value
    processed_end = len(value)
    for finding in sorted(findings, key=lambda item: item.char_offset, reverse=True):
        if finding.char_end > processed_end:
            continue
        placeholder = f"[REDACTED:{finding.pattern_type.value}]"
        result = result[: finding.char_offset] + placeholder + result[finding.char_end :]
        processed_end = finding.char_offset
        counts[finding.pattern_type.value] += 1

    return result, dict(counts)


def _merge_count_maps(first: dict[str, Any], second: dict[str, int]) -> dict[str, int]:
    merged = Counter({str(key): int(value) for key, value in first.items()})
    merged.update(second)
    return dict(merged)


def _display_path(file_path: Path) -> str:
    for root in (WORKSPACE_ROOT, PROJECT_ROOT):
        try:
            return str(file_path.relative_to(root))
        except ValueError:
            continue
    return str(file_path)


def _display_root(root: Path) -> str:
    for base in (WORKSPACE_ROOT, PROJECT_ROOT):
        try:
            relative = root.relative_to(base)
            return "." if str(relative) == "." else str(relative)
        except ValueError:
            continue
    return str(root)


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
