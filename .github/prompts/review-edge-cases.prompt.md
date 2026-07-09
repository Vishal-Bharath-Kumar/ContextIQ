---
agent: agent
description: Systematically analyzes an artifact to surface boundary conditions and failure modes across input, state, concurrency, and integration dimensions.
tools: ['execute/getTerminalOutput', 'execute/createAndRunTask', 'execute/runInTerminal', 'read/problems', 'read/readFile', 'edit/createDirectory', 'edit/createFile', 'edit/editFiles', 'search', 'web', 'azure-mcp/search', 'context7/*', 'sequential-thinking/*', 'todo', propel-sdlc/*]
---

consult `.propel/prompts/review-edge-cases.md` for the workflow steps.

---

*This workflow produces severity-ranked edge case findings with clear reproduction context for downstream remediation.*
