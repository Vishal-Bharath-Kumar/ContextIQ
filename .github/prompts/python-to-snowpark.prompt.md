---
agent: agent
description: Converts Python code to Snowpark-compatible code immediately without planning artifacts.
tools: ['execute/getTerminalOutput', 'execute/createAndRunTask', 'execute/runInTerminal', 'read/problems', 'read/readFile', 'edit/createDirectory', 'edit/createFile', 'edit/editFiles', 'search', 'web', 'azure-mcp/search', 'sequential-thinking/*', 'todo', propel-sdlc/*]
---

consult `.propel/prompts/python-to-snowpark.md` for the workflow steps.

---

*This converter produces Snowpark-compatible Python for Data Engineers.*
