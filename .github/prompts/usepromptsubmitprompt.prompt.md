---
mode: ask
model: GPT-5.3-Codex
description: Copilot Chat workaround for usepromptsubmitprompt-style session tracking.
---

Use this workflow before sending your main request:

1. Run VS Code task `PropelIQ: Copilot pre-prompt submit`.
2. Paste your actual request right after this prompt.
3. When ending the chat session, run task `PropelIQ: Copilot session end`.

Context:
- GitHub Copilot Chat in VS Code does not expose hook events equivalent to `UserPromptSubmit`/`Stop`.
- These tasks call `.propel/hooks/context_tracker_tiktoken/copilot.py` with equivalent events.

Now proceed with the user request that follows.
