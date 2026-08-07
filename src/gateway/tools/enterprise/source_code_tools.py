"""Source code search and analysis tools.

TASK-BRD-18: Implements MCP tools for source code capabilities:
- search_code: Search across repositories
- explain_code: Get code explanations with context
- search_repository: Repository-specific search
"""
from __future__ import annotations

from datetime import UTC, datetime
from fnmatch import fnmatch
import logging
from pathlib import PurePosixPath
from typing import Any

from fastmcp import FastMCP
from opensearchpy import AsyncOpenSearch
from sqlalchemy import select
from src.data.database import primary_session_factory
from src.gateway.tools.enterprise._local_tools import (
    CODE_ROOTS,
    _LANGUAGE_SUFFIXES,
    build_error_response,
    build_tool_response,
    explain_code_file,
    json_text_response,
    search_workspace,
    workspace_coverage,
)
from src.indexing.stores.opensearch_indexer import OpenSearchSettings
from src.knowledge_sources.models.knowledge_source import KnowledgeSourceRecord
from mcp.types import TextContent

logger = logging.getLogger(__name__)

_INDEX_QUERY_EXPANSION = 5


async def _resolve_repository_source(repository: str) -> tuple[str | None, dict[str, Any]]:
    normalized = repository.strip().lower()
    if not normalized:
        return None, {
            "resolved": False,
            "resolution_method": "missing_repository",
            "repository": repository,
            "degraded_reasons": ["Repository name was empty; indexed repository search was skipped."],
        }

    async with primary_session_factory()() as session:
        result = await session.execute(
            select(
                KnowledgeSourceRecord.id,
                KnowledgeSourceRecord.scope,
                KnowledgeSourceRecord.name,
            ).where(
                KnowledgeSourceRecord.connector_type == "github",
                KnowledgeSourceRecord.is_active == True,  # noqa: E712
            )
        )
        rows = result.all()

    suffix_matches: list[tuple[str, str]] = []
    name_matches: list[tuple[str, str]] = []
    for source_id, scope, name in rows:
        scope_text = str(scope or "")
        name_text = str(name or "")
        if scope_text.lower() == normalized:
            return str(source_id), {
                "resolved": True,
                "resolution_method": "scope_exact",
                "repository": repository,
                "matched_scope": scope_text,
                "source_id": str(source_id),
                "degraded_reasons": [],
            }
        if name_text and name_text.lower() == normalized:
            name_matches.append((str(source_id), scope_text))
        if scope_text.rsplit("/", 1)[-1].lower() == normalized:
            suffix_matches.append((str(source_id), scope_text))

    if len(name_matches) == 1:
        source_id, scope_text = name_matches[0]
        return source_id, {
            "resolved": True,
            "resolution_method": "name_exact",
            "repository": repository,
            "matched_scope": scope_text,
            "source_id": source_id,
            "degraded_reasons": [],
        }

    if len(suffix_matches) == 1:
        source_id, scope_text = suffix_matches[0]
        return source_id, {
            "resolved": True,
            "resolution_method": "scope_suffix_unique",
            "repository": repository,
            "matched_scope": scope_text,
            "source_id": source_id,
            "degraded_reasons": [],
        }

    if len(suffix_matches) > 1:
        return None, {
            "resolved": False,
            "resolution_method": "scope_suffix_ambiguous",
            "repository": repository,
            "matches": [scope for _source_id, scope in suffix_matches],
            "degraded_reasons": [
                "Repository name matched multiple active GitHub knowledge-source scopes; use the full owner/repo identifier.",
            ],
        }

    return None, {
        "resolved": False,
        "resolution_method": "not_found",
        "repository": repository,
        "degraded_reasons": [
            "No active GitHub knowledge source matched the supplied repository identifier.",
        ],
    }


def _build_index_query(query: str, source_id: str, top_k: int) -> dict[str, Any]:
    stripped = query.strip()
    if stripped in {"", "*"}:
        query_clause: dict[str, Any] = {"match_all": {}}
    else:
        tokens = [token for token in stripped.replace("/", " ").split() if token and token != "*"]
        should_clauses: list[dict[str, Any]] = [
            {
                "multi_match": {
                    "query": stripped,
                    "fields": ["text^2", "document_id", "metadata.file_path"],
                    "type": "best_fields",
                }
            }
        ]
        for token in tokens:
            should_clauses.extend(
                [
                    {
                        "wildcard": {
                            "document_id": {
                                "value": f"*{token}*",
                                "case_insensitive": True,
                            }
                        }
                    },
                    {
                        "wildcard": {
                            "metadata.file_path": {
                                "value": f"*{token}*",
                                "case_insensitive": True,
                            }
                        }
                    },
                    {
                        "wildcard": {
                            "metadata.file_path.keyword": {
                                "value": f"*{token}*",
                                "case_insensitive": True,
                            }
                        }
                    },
                ]
            )
        query_clause = {
            "bool": {
                "should": should_clauses,
                "minimum_should_match": 1,
            }
        }

    return {
        "size": top_k,
        "query": {
            "bool": {
                "must": [query_clause],
                "filter": [{"term": {"source_id": source_id}}],
            }
        },
        "_source": ["document_id", "text", "metadata", "source_id"],
    }


def _document_path(document_id: str) -> str:
    parts = document_id.split(":", 2)
    if len(parts) == 3:
        return parts[2]
    return document_id


def _path_matches(file_path: str, path_filter: str | None) -> bool:
    if not path_filter:
        return True
    return fnmatch(file_path, path_filter) or PurePosixPath(file_path).match(path_filter)


def _suffix_matches(file_path: str, suffixes: set[str] | None) -> bool:
    if not suffixes:
        return True
    return PurePosixPath(file_path).suffix.lower() in suffixes


def _matched_terms(query: str, file_path: str, snippet: str) -> list[str]:
    haystack = f"{file_path}\n{snippet}".lower()
    tokens = [token for token in query.lower().split() if token not in {"*"}]
    return [token for token in tokens if token in haystack][:10]


async def _search_indexed_repository(
    *,
    repository: str,
    query: str,
    limit: int,
    language: str | None = None,
    path_filter: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_id, resolution = await _resolve_repository_source(repository)
    if source_id is None:
        return [], {
            "adapter": "indexed_repository_resolution",
            "source_availability": resolution,
            "degraded_reasons": list(resolution.get("degraded_reasons") or []),
        }

    suffixes = _LANGUAGE_SUFFIXES.get(language.lower()) if language else None
    settings = OpenSearchSettings()
    client = AsyncOpenSearch(
        hosts=[settings.url],
        http_auth=(settings.username, settings.password),
        use_ssl=settings.url.startswith("https"),
        verify_certs=False,
    )

    try:
        response = await client.search(
            index=f"{settings.index_prefix}_*",
            body=_build_index_query(query, source_id, max(limit * _INDEX_QUERY_EXPANSION, limit)),
        )
    finally:
        await client.close()

    deduped: dict[str, dict[str, Any]] = {}
    for hit in response.get("hits", {}).get("hits", []):
        payload = hit.get("_source") or {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        document_id = str(payload.get("document_id") or "")
        file_path = str(metadata.get("file_path") or _document_path(document_id) or document_id)
        if not file_path or not _path_matches(file_path, path_filter) or not _suffix_matches(file_path, suffixes):
            continue

        snippet = str(payload.get("text") or "").strip()
        if not snippet:
            continue

        score = float(hit.get("_score") or 0.0)
        existing = deduped.get(file_path)
        if existing is not None and existing["score"] >= score:
            continue

        deduped[file_path] = {
            "path": file_path,
            "title": PurePosixPath(file_path).name or file_path,
            "line": 1,
            "snippet": snippet[:2000],
            "score": round(score, 3),
            "matched_terms": _matched_terms(query, file_path, snippet),
            "last_modified": metadata.get("timestamp") or datetime.now(UTC).isoformat(),
            "document_id": document_id,
        }

    matches = sorted(deduped.values(), key=lambda item: (-item["score"], item["path"]))[:limit]
    diagnostics = {
        "adapter": "opensearch_index_search",
        "source_availability": {
            **resolution,
            "index": f"{settings.index_prefix}_*",
            "path_filter": path_filter,
            "language": language or "all languages",
        },
        "degraded_reasons": list(resolution.get("degraded_reasons") or []),
    }
    return matches, diagnostics


def register_source_code_tools(mcp: FastMCP, connector_manager: Any = None) -> None:
    """Register source code tools on the MCP server.
    
    Parameters
    ----------
    mcp:
        FastMCP server instance
    connector_manager:
        Connector manager for accessing GitHub/GitLab connectors
    """

    @mcp.tool()
    async def search_code(
        query: str,
        repository: str | None = None,
        language: str | None = None,
        limit: int = 10,
    ) -> list[TextContent]:
        """Search for code across enterprise repositories.
        
        Searches through indexed source code using semantic and keyword search.
        Returns relevant code snippets with file paths, line numbers, and context.
        
        Parameters
        ----------
        query:
            Search query (natural language or code pattern)
        repository:
            Optional repository name to scope the search
        language:
            Optional programming language filter (python, typescript, java, etc.)
        limit:
            Maximum number of results (default: 10)
            
        Returns
        -------
        list[TextContent]:
            Code search results with snippets and metadata
        """
        try:
            suffixes = None
            if language:
                suffixes = _LANGUAGE_SUFFIXES.get(language.lower())

            diagnostics: dict[str, Any]
            if repository:
                try:
                    matches, diagnostics = await _search_indexed_repository(
                        repository=repository,
                        query=query,
                        limit=limit,
                        language=language,
                    )
                except Exception as exc:
                    logger.warning("indexed search_code failed for repository=%s", repository, exc_info=True)
                    matches = search_workspace(query, roots=CODE_ROOTS, suffixes=suffixes, limit=limit)
                    diagnostics = {
                        "adapter": "workspace_search",
                        "source_availability": workspace_coverage(roots=CODE_ROOTS, suffixes=suffixes),
                        "degraded_reasons": [
                            f"Indexed repository search failed: {type(exc).__name__}: {str(exc)[:160]}",
                        ],
                    }
            else:
                matches = search_workspace(query, roots=CODE_ROOTS, suffixes=suffixes, limit=limit)
                diagnostics = {
                    "adapter": "workspace_search",
                    "source_availability": workspace_coverage(roots=CODE_ROOTS, suffixes=suffixes),
                    "degraded_reasons": [],
                }

            results = build_tool_response(
                status="success" if matches else "empty",
                summary=(
                    f"Found {len(matches)} code match(es)."
                    if matches
                    else "No code matches were found for the supplied query."
                ),
                data={
                    "query": query,
                    "repository": repository or "ContextIQ",
                    "language": language or "all languages",
                    "results": matches,
                    "total": len(matches),
                },
                diagnostics=diagnostics,
            )
            results.update(
                {
                    "query": query,
                    "repository": repository or "ContextIQ",
                    "language": language or "all languages",
                    "results": matches,
                    "total": len(matches),
                }
            )
            
            logger.info(
                "search_code invoked: query=%s, repo=%s, lang=%s",
                query,
                repository,
                language,
            )
            
            return json_text_response(results)
            
        except Exception as e:
            logger.error("search_code failed: %s", e, exc_info=True)
            return json_text_response(
                build_error_response(
                    summary="Code search failed.",
                    error=e,
                    diagnostics={"adapter": "workspace_search"},
                )
            )

    @mcp.tool()
    async def explain_code(
        file_path: str,
        repository: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> list[TextContent]:
        """Get AI-generated explanation of code with enterprise context.
        
        Retrieves code from a specific file and generates a detailed explanation
        including architecture context, dependencies, and relationships.
        
        Parameters
        ----------
        file_path:
            Path to the file within the repository
        repository:
            Repository name
        start_line:
            Optional start line number for specific code block
        end_line:
            Optional end line number for specific code block
            
        Returns
        -------
        list[TextContent]:
            Code explanation with architecture context
        """
        try:
            explanation = explain_code_file(file_path, start_line=start_line, end_line=end_line)
            result = build_tool_response(
                status="success",
                summary="Generated a code explanation from the local workspace file.",
                data={**explanation, "repository": repository},
                diagnostics={"adapter": "workspace_file_read", "degraded_reasons": []},
            )
            result.update({**explanation, "repository": repository})
            
            logger.info(
                "explain_code invoked: %s in %s (lines %s-%s)",
                file_path,
                repository,
                start_line,
                end_line,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("explain_code failed: %s", e, exc_info=True)
            return json_text_response(
                build_error_response(
                    summary="Code explanation failed.",
                    error=e,
                    diagnostics={"adapter": "workspace_file_read", "file_path": file_path},
                )
            )

    @mcp.tool()
    async def search_repository(
        repository: str,
        query: str,
        path_filter: str | None = None,
    ) -> list[TextContent]:
        """Search within a specific repository.
        
        Optimized search scoped to a single repository with optional path filtering.
        
        Parameters
        ----------
        repository:
            Repository name to search
        query:
            Search query
        path_filter:
            Optional path pattern (e.g., "src/**/*.py")
            
        Returns
        -------
        list[TextContent]:
            Repository search results
        """
        try:
            try:
                matches, diagnostics = await _search_indexed_repository(
                    repository=repository,
                    query=query,
                    limit=20,
                    path_filter=path_filter,
                )
            except Exception as exc:
                logger.warning("indexed search_repository failed for repository=%s", repository, exc_info=True)
                matches = search_workspace(
                    query,
                    roots=CODE_ROOTS,
                    suffixes=None,
                    limit=20,
                    path_filter=path_filter,
                )
                diagnostics = {
                    "adapter": "workspace_search",
                    "source_availability": workspace_coverage(roots=CODE_ROOTS, path_filter=path_filter),
                    "degraded_reasons": [
                        f"Indexed repository search failed: {type(exc).__name__}: {str(exc)[:160]}",
                    ],
                }
            result = build_tool_response(
                status="success" if matches else "empty",
                summary=(
                    f"Found {len(matches)} repository match(es)."
                    if matches
                    else "No repository matches were found for the supplied query."
                ),
                data={
                    "repository": repository or "ContextIQ",
                    "query": query,
                    "path_filter": path_filter,
                    "results": matches,
                },
                diagnostics=diagnostics,
            )
            result.update(
                {
                    "repository": repository or "ContextIQ",
                    "query": query,
                    "path_filter": path_filter,
                    "results": matches,
                }
            )
            
            logger.info(
                "search_repository invoked: %s in %s (filter: %s)",
                query,
                repository,
                path_filter,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("search_repository failed: %s", e, exc_info=True)
            return json_text_response(
                build_error_response(
                    summary="Repository search failed.",
                    error=e,
                    diagnostics={"adapter": "workspace_search", "path_filter": path_filter},
                )
            )
