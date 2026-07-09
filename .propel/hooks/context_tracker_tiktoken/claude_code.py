#!/usr/bin/env python3
"""Claude Code adapter. Wire both UserPromptSubmit and Stop to this script."""
import sys

from core import HookEvent, PHASE_POST, PHASE_PRE, dispatch, read_stdin_json


def main() -> None:
    data = read_stdin_json()
    event_name = data.get("hook_event_name", "")
    phase = {"UserPromptSubmit": PHASE_PRE, "Stop": PHASE_POST}.get(event_name)
    if phase is None:
        sys.exit(0)

    dispatch(
        HookEvent(
            ide="claude-code",
            phase=phase,
            session_id=data.get("session_id", "unknown"),
            transcript_path=data.get("transcript_path"),
            prompt=data.get("prompt"),
            model=data.get("model") or (data.get("message") or {}).get("model"),
        )
    )
    sys.exit(0)


if __name__ == "__main__":
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
