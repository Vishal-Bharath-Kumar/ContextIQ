---
agent: agent
description: Executes unit tests scoped to a user story, test plan, or development task with zero-setup framework detection, coverage enforcement, and actionable diagnostics.
tools: ['execute/testFailure', 'execute/getTerminalOutput', 'execute/createAndRunTask', 'execute/runInTerminal', 'read/problems', 'read/readFile', 'read/terminalSelection', 'read/terminalLastCommand', 'edit/createDirectory', 'edit/createFile', 'edit/editFiles', 'search', 'web', 'azure-mcp/search', 'context7/*', 'sequential-thinking/*', 'todo', propel-sdlc/*]
---

consult `.propel/prompts/execute-unittest.md` for the workflow steps.

---

*This workflow reports pass/fail counts, coverage by file, failure diagnostics, and a quality-gated verdict on test health.*
