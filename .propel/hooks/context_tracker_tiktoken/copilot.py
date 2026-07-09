#!/usr/bin/env python3
"""
GitHub Copilot CLI adapter.

Copilot does not expose a per-turn Stop event or a transcript file, so we:
  - treat `userPromptSubmitted` as a PRE event that accumulates prompt tokens
  - treat `sessionEnd` as a POST event that reports the cumulative total

Copilot does not emit a session id, so we synthesise one from:
  - the Copilot CLI process id (os.getppid — stable for the lifetime of the
    CLI session; distinguishes concurrent sessions in the same directory)
  - the working directory (distinguishes sessions across projects)
The resulting key is `<ppid>-<basename-of-cwd>` and is passed to core via
HookEvent.session_id. Override with the COPILOT_SESSION_ID env var if the
Copilot CLI ever starts exposing a real id.
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import HookEvent, PHASE_POST, PHASE_PRE, dispatch, read_stdin_json  # noqa: E402


def _session_id(data: dict) -> str:
    override = os.environ.get("COPILOT_SESSION_ID")
    if override:
        return override
    cwd = data.get("cwd") or os.getcwd()
    ppid = os.getppid()
    # Short cwd hash keeps the filename readable while still disambiguating
    # two projects that happen to share a basename.
    cwd_hash = hashlib.sha1(cwd.encode("utf-8")).hexdigest()[:8]
    return f"copilot-{ppid}-{os.path.basename(cwd) or 'root'}-{cwd_hash}"


def main() -> None:
    data = read_stdin_json()
    # Copilot does not include an explicit event name field; adapters are
    # registered per-event, so the caller passes the event via argv.
    event_name = sys.argv[1] if len(sys.argv) > 1 else ""

    prompt = data.get("prompt", "") or ""
    model = data.get("model") or os.environ.get("COPILOT_MODEL")

    if event_name == "userPromptSubmitted":
        dispatch(
            HookEvent(
                ide="copilot",
                phase=PHASE_PRE,
                session_id=_session_id(data),
                inline_text=prompt,
                prompt=prompt,
                model=model,
            )
        )
    elif event_name == "sessionEnd":
        dispatch(
            HookEvent(
                ide="copilot",
                phase=PHASE_POST,
                session_id=_session_id(data),
                inline_text="",  # no transcript; post reuses accumulated pre total
                model=model,
            )
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
