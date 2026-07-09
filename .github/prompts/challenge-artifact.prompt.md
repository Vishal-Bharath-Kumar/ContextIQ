---
agent: agent
description: Adversarial critique of a specified artifact (spec, design, epics) surfacing hidden assumptions, contradictions, gaps, and upstream cross-reference mismatches.
tools: ['execute/getTerminalOutput', 'execute/createAndRunTask', 'execute/runInTerminal', 'read/problems', 'read/readFile', 'edit/createDirectory', 'edit/createFile', 'edit/editFiles', 'search', 'web', 'azure-mcp/search', 'context7/*', 'sequential-thinking/*', 'todo', propel-sdlc/*]
---

consult `.propel/prompts/challenge-artifact.md` for the workflow steps.

---

*This workflow produces severity-ranked findings and a clear verdict of APPROVE, NEEDS ATTENTION, or REJECT.*
