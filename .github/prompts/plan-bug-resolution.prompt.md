---
agent: agent
description: Performs comprehensive bug triage, root cause analysis, and generates fix implementation tasks with validation criteria.
tools: ['execute/getTerminalOutput', 'execute/createAndRunTask', 'execute/runInTerminal', 'read/problems', 'read/readFile', 'edit/createDirectory', 'edit/createFile', 'edit/editFiles', 'search', 'web', 'azure-mcp/search', 'context7/*', 'sequential-thinking/*', 'todo', propel-sdlc/*]
---

consult `.propel/prompts/plan-bug-resolution.md` for the workflow steps.

---

*This workflow performs bug triage, root cause analysis, and generates fix tasks with validation criteria.*
