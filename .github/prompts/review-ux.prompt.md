---
agent: agent
description: Heuristic UX review of UI source files applying Krug's laws, Nielsen's 10 heuristics, and dark-pattern detection with optional persona-scoped findings.
tools: ['execute/testFailure', 'execute/getTerminalOutput', 'execute/runInTerminal', 'read/problems', 'read/readFile', 'read/terminalSelection', 'read/terminalLastCommand', 'edit/createDirectory', 'edit/createFile', 'edit/editFiles', 'search', 'web', 'azure-mcp/search', 'playwright/*', 'context7/*', 'sequential-thinking/*', 'figma/*', 'todo', propel-sdlc/*]
---

consult `.propel/prompts/review-ux.md` for the workflow steps.

---

*This workflow produces severity-ranked usability findings scoped by heuristic category and optional persona journey.*
