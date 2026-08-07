---
agent: agent
description: Query enterprise context through the configured ContextIQ MCP server from Copilot Chat.
---

Use this slash command to route the current request through ContextIQ.

Instructions:
- Treat the text after `/contextiq` as the user's actual request.
- Prefer ContextIQ MCP tools before generic workspace search when the request is about enterprise documentation, repository search, architecture, ownership, dependencies, service health, logs, governance, or synced knowledge sources.
- Choose the narrowest useful ContextIQ tool first. Use broader search or context-generation tools only when a focused tool is not sufficient.
- If ContextIQ does not return enough information, fall back to local workspace tools and say briefly that you fell back.
- Keep answers concise and evidence-based. When useful, end with one more specific `/contextiq ...` query the user can run next.