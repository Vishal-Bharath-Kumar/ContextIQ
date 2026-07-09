#!/usr/bin/env python3
"""
Windsurf Cascade adapter.

Wire pre_user_prompt and post_cascade_response_with_transcript to this
script (pass the event name as argv[1] from the hook command).
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import HookEvent, PHASE_POST, PHASE_PRE, dispatch, read_stdin_json  # noqa: E402

ALWAYS_LOG_RAW = os.environ.get("HOOK_ALWAYS_LOG", "1") == "1"  # Default ON for diagnostics


def _always_log_raw_data(event_name: str, data: dict, extracted_prompt: str) -> None:
    """Always log raw stdin for debugging empty content issues."""
    if not ALWAYS_LOG_RAW:
        return
    try:
        log_dir = Path(__file__).resolve().parents[2] / "telemetry"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "windsurf-raw-data.log"
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Event: {event_name}\n")
            f.write(f"Extracted Prompt: {repr(extracted_prompt)}\n")
            f.write(f"Prompt Length: {len(extracted_prompt)} chars\n")
            f.write(f"Variant: estimate (char/4)\n")
            f.write(f"Raw stdin JSON:\n{json.dumps(data, indent=2)}\n")
    except Exception as e:
        print(f"[windsurf] Failed to write raw data log: {e}", file=sys.stderr)


def main() -> None:
    data = read_stdin_json()
    event_name = sys.argv[1] if len(sys.argv) > 1 else ""
    tool_info = data.get("tool_info", {}) or {}
    session_id = data.get("trajectory_id") or data.get("execution_id") or "unknown"
    model = data.get("model_name") or data.get("model")
    prompt = tool_info.get("user_prompt", "") or tool_info.get("prompt", "") or ""
    
    # Always log raw data for diagnostics
    _always_log_raw_data(event_name, data, prompt)
    
    # Warn if prompt is empty for user input events
    if not prompt and event_name == "pre_user_prompt":
        print(f"[windsurf] WARNING: Empty prompt extracted from {event_name}", file=sys.stderr)
        print(f"[windsurf] Data keys present: {list(data.keys())}", file=sys.stderr)
        if "tool_info" in data:
            print(f"[windsurf] tool_info keys: {list(data['tool_info'].keys())}", file=sys.stderr)

    if event_name == "pre_user_prompt":
        dispatch(
            HookEvent(
                ide="windsurf",
                phase=PHASE_PRE,
                session_id=session_id,
                inline_text=prompt,
                prompt=prompt,
                model=model,
            )
        )
    elif event_name in ("post_cascade_response_with_transcript", "post_cascade_response"):
        dispatch(
            HookEvent(
                ide="windsurf",
                phase=PHASE_POST,
                session_id=session_id,
                transcript_path=tool_info.get("transcript_path"),
                inline_text=tool_info.get("response", ""),
                model=model,
            )
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
