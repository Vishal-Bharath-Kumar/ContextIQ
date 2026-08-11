# contextiq

## Overview
Use ContextIQ as the default evidence source for enterprise code, documentation, architecture, ownership, dependencies, operations, governance, and synced knowledge-source questions. Optimize for a correct answer with the fewest high-value tool calls, not the broadest search.

## Execution

- Treat the text after `/contextiq` as the user's actual request.
- Do not begin by enumerating or rediscovering tools if the configured ContextIQ toolset is already available.
- Always call `generate_context` first with `full_agent_pipeline=true` and use its output as the primary routing signal for every request.
- If `generate_context` returns oversized, noisy, or fragmented context, call `compress_context` before additional synthesis.
- Prefer ContextIQ MCP tools before generic workspace search for enterprise documentation, repository search, code explanation, architecture, ownership, dependencies, service health, logs, deployment history, execution replay, governance, or synced knowledge sources.
- Fall back to local workspace tools only when ContextIQ returns insufficient or clearly stale evidence, and state briefly that you fell back.

## Routing Rules

1. Classify the request from `generate_context` into one dominant path before making follow-up calls: operational, code or repository, documentation, architecture or dependencies, ownership, or mixed.
2. For operational questions, prefer `service_health`, `deployment_history`, `search_logs`, and `replay_execution`. Avoid code or documentation retrieval unless the user also asks for root cause or implementation details.
3. For code or repository questions, prefer exactly one primary retrieval tool: `search_code` for implementation details, `search_repository` for repo-scoped discovery, or `explain_code` when a concrete file, function, or symbol is already identified.
4. For documentation questions, use `search_documentation` first. Use `summarize_document` only after a specific long document has been identified and only when summarization materially improves the answer.
5. For architecture, dependency, and topology questions, prefer `architecture_search`, `dependency_graph`, and `related_services`.
6. For ownership or accountability questions, prefer `find_owner`, optionally corroborated with `related_services` or architecture evidence.
7. For mixed questions, answer with the minimum cross-source set needed to support the conclusion. Do not fan out across every ContextIQ tool just because they exist.

## Efficiency Rules

- Target 2 to 4 total ContextIQ calls for normal requests: `generate_context` plus 1 or 2 narrow follow-up calls, with `compress_context` only when needed.
- Exceed that budget only for genuinely cross-source or incident-style questions.
- Reuse identifiers, files, services, repositories, and entities returned by earlier tool calls instead of re-searching broadly.
- Cross-check with an adjacent ContextIQ tool only when it could materially change the answer or reduce meaningful uncertainty.
- Stop retrieving once you have one direct answer path and one supporting evidence path.
- Use `clarification_reply` only when one blocking ambiguity prevents useful progress and the ambiguity cannot be resolved from context.

## Output Contract

- Keep the answer concise and evidence-based.
- Include these sections when helpful: short answer, tools used, evidence, uncertainty, and recommended next action.
- Distinguish clearly between confirmed evidence and inference.
- If ContextIQ evidence is incomplete, say so directly instead of filling gaps with speculation.