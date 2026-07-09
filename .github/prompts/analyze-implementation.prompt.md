---
agent: agent
description: Reviews implementation against task file requirements to verify scope alignment, identify gaps, and generate task-review reports with actionable recommendations.
tools: ['execute/getTerminalOutput', 'execute/createAndRunTask', 'execute/runInTerminal', 'read/problems', 'read/readFile', 'edit/createDirectory', 'edit/createFile', 'edit/editFiles', 'search', 'web', 'azure-mcp/search', 'context7/*', 'sequential-thinking/*', 'todo', propel-sdlc/*]
---

consult `.propel/prompts/analyze-implementation.md` for the workflow steps.

---

*This analyzer reviews implementation against task requirements to verify scope alignment and provide actionable recommendations.*
