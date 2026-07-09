# Multi-IDE Context Tracker

Reports per-request and cumulative token usage for **Claude Code**, **GitHub Copilot CLI**, and **Windsurf (Cascade)** from a single shared core.

## Layout

```
.propel/hooks/
├── context_tracker_tiktoken/     # tiktoken-backed (higher accuracy)
│   ├── core.py
│   ├── claude_code.py            # Claude Code adapter (UserPromptSubmit / Stop)
│   ├── copilot.py                # Copilot CLI adapter (userPromptSubmitted / sessionEnd)
│   └── windsurf.py               # Windsurf adapter (pre_user_prompt / post_cascade_response_*)
├── context_tracker_estimate/     # zero-dependency char/4 estimate
│   ├── core.py
│   ├── claude_code.py
│   ├── copilot.py
│   └── windsurf.py
└── configs/
    ├── claude-code.settings.json
    ├── copilot.hooks.json
    └── windsurf.hooks.json
```

## Which variant to use

Both variants write the **same** per-session trace file shape under
`.propel/telemetry/ctx-tracing-<session-id>.json` (OpenTelemetry GenAI
semantic conventions, structured messages, user info, latency, redaction).
Only token-count accuracy and the `context_window.counting_method` field
differ.

| Variant | Dependencies | Token accuracy | When to pick |
|---|---|---|---|
| `context_tracker_tiktoken/` | `pip install tiktoken` | ~90–95% vs Claude's real tokenizer (BPE `p50k_base` proxy) | **Default.** Use when the Python the IDE invokes can install one small wheel. |
| `context_tracker_estimate/` | stdlib only | ~70–85%, drifts on code/non-English | Locked-down machines, CI sandboxes, or when you want a self-contained hook with zero pip installs. |

Switching variants is a one-line path swap in `.claude/settings.json` (or
the Copilot / Windsurf hook config): replace `context_tracker_tiktoken`
with `context_tracker_estimate` in the command. The same session keeps
accumulating turns in the same file — only newly written turns will show
the flipped `counting_method`.

## Install

```bash
pip install tiktoken   # only needed for the tiktoken variant
```

Set `CONTEXT_TRACKER_LIMIT` to override the default 128,000-token context window.

## Wire up each IDE

### Claude Code
Merge `configs/claude-code.settings.json` into `.claude/settings.json` (project) or `~/.claude/settings.json` (user). Hooks fire on `UserPromptSubmit` and `Stop`; the adapter uses the transcript file Claude Code passes via `transcript_path`.

### GitHub Copilot CLI
Copy `configs/copilot.hooks.json` to your Copilot CLI hooks config location (see [GitHub docs](https://docs.github.com/en/copilot/reference/hooks-configuration)). Copilot does not expose a transcript or per-turn Stop event, so the adapter accumulates prompt tokens at `userPromptSubmitted` and reports the session total at `sessionEnd`. A per-turn Stop event is tracked in [copilot-cli#1157](https://github.com/github/copilot-cli/issues/1157) — when it ships, add a `stop` entry to the config pointing at `copilot.py stop`.

### Windsurf
Copy `configs/windsurf.hooks.json` to `.windsurf/hooks.json` (workspace) or `~/.codeium/windsurf/hooks.json` (user). The adapter reads the JSONL transcript from `tool_info.transcript_path` on `post_cascade_response_with_transcript`.

## How it works

Each adapter normalises its IDE's stdin payload into a `HookEvent(ide, phase, session_id, transcript_path | inline_text)` and calls `core.dispatch`. Core writes a pre-phase token count to a per-IDE, per-session temp file and reports the delta at the post phase. Output goes to stderr so it does not interfere with hook decision JSON.

## Accuracy note

Anthropic has not released an offline tokenizer. The tiktoken variant uses
`p50k_base` BPE encoding as a proxy (~90–95% of Claude's actual count). The
estimate variant uses a 4-chars-per-token heuristic (~70–85%).

## Sources

- [Claude Code hooks reference](https://code.claude.com/docs/en/hooks)
- [GitHub Copilot hooks configuration](https://docs.github.com/en/copilot/reference/hooks-configuration)
- [Windsurf Cascade hooks](https://docs.windsurf.com/windsurf/cascade/hooks)
