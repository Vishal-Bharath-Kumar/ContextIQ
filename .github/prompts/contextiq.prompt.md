---
agent: agent
description: Use the configured ContextIQ MCP server from Copilot Chat to discover and invoke enterprise code, documentation, operations, graph, and AI context tools.
---

Use this slash command to handle the current request through ContextIQ.

Instructions:
- Treat the text after `/contextiq` as the user's actual request.
- Start by discovering the available ContextIQ MCP tools, then always invoke `generate_context` for the full `/contextiq` request before selecting follow-on tools.
- Prefer ContextIQ MCP tools before generic workspace search when the request involves enterprise documentation, repository search, code explanation, architecture, ownership, dependencies, service health, logs, deployment history, execution replay, governance, or synced knowledge sources.
- Use the `generate_context` output as the primary routing context, then use the narrowest useful ContextIQ tool for follow-up evidence and cross-check with adjacent ContextIQ tools when that materially improves confidence.
- Use the full ContextIQ capability set when relevant, including `search_code`, `explain_code`, `search_repository`, `search_documentation`, `summarize_document`, `architecture_search`, `search_logs`, `deployment_history`, `service_health`, `dependency_graph`, `find_owner`, `related_services`, `generate_context`, `compress_context`, and `replay_execution`.
- Use `clarification_reply` only when one blocking clarification is required to continue.
- If the request spans multiple evidence sources, correlate findings across code, docs, architecture, operations, dependencies, and ownership instead of relying on a single result.
- Always run `generate_context` before producing the answer. If the resulting context is still large or fragmented, use `compress_context` before the final answer.
- If ContextIQ does not return enough information, fall back to local workspace tools and say briefly that you fell back.
- Keep answers concise and evidence-based. Include: short answer, tools used, evidence, uncertainty, and recommended next action when helpful.