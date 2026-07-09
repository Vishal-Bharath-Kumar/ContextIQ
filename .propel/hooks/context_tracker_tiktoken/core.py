"""
Shared core for the multi-IDE context-usage tracker.

Per-session trace files are written to
  .propel/telemetry/ctx-tracing-<session-id>.json
and are aligned with the OpenTelemetry GenAI semantic conventions
(https://opentelemetry.io/docs/specs/semconv/gen-ai/). Each user turn is a
single entry in `turns[]`, opened at PRE and closed at POST.

Token counting uses tiktoken's p50k_base encoding when available (~90-95%
accuracy against Claude's tokenizer) and falls back to a 4-chars-per-token
estimate otherwise. Anthropic has not shipped an official offline tokenizer;
both Claude and GPT models use BPE, so p50k_base is a reasonable proxy.
"""
from __future__ import annotations

import getpass
import json
import os
import platform
import re
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import tiktoken

    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_AVAILABLE = False

_DEFAULT_CONTEXT_LIMIT = 128_000
_CONTEXT_LIMIT_OVERRIDE = os.environ.get("CONTEXT_TRACKER_LIMIT")


def _resolve_context_limit(model: Optional[str]) -> int:
    """Resolve the context-window size for a given model.

    Precedence:
      1. CONTEXT_TRACKER_LIMIT env var (explicit override).
      2. Model-name pattern match (1M, 200k, 128k tiers).
      3. _DEFAULT_CONTEXT_LIMIT (128k).
    """
    if _CONTEXT_LIMIT_OVERRIDE:
        try:
            return int(_CONTEXT_LIMIT_OVERRIDE)
        except ValueError:
            pass
    if not model:
        return _DEFAULT_CONTEXT_LIMIT

    m = model.lower()

    if "[1m]" in m or re.search(r"\b1m\b", m) or m.endswith("-1m"):
        return 1_000_000

    if "claude" in m:
        return 200_000

    if any(tag in m for tag in ("gpt-4o", "gpt-4.1", "o1", "o3", "o4")):
        return 128_000

    if "gemini" in m:
        return 2_000_000 if "-2m" in m else 1_000_000

    return _DEFAULT_CONTEXT_LIMIT


MAX_MESSAGE_CHARS = int(os.environ.get("CTX_TRACKER_MAX_MESSAGE_CHARS", "8000"))
REDACT_ENABLED = os.environ.get("CTX_TRACKER_REDACT") == "1"

_PROPEL_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _PROPEL_DIR.parent
TELEMETRY_DIR = Path(os.environ.get("CONTEXT_TRACKER_LOG_DIR", _PROPEL_DIR / "telemetry"))
OTEL_SCHEMA_URL = "https://opentelemetry.io/schemas/1.36.0"

PHASE_PRE = "pre"
PHASE_POST = "post"

# Always-on PII patterns. Emails are stripped unconditionally per user request.
_ALWAYS_REDACT_PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email>"),
]
# Opt-in patterns enabled via CTX_TRACKER_REDACT=1.
_OPTIONAL_REDACT_PATTERNS = [
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<aws-access-key>"),
    (re.compile(r"\b(?:Bearer|token)[= ]+[A-Za-z0-9._\-]{16,}\b", re.IGNORECASE), "<token>"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "<api-key>"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"), "<github-token>"),
]


@dataclass
class HookEvent:
    ide: str
    phase: str
    session_id: str
    transcript_path: Optional[str] = None
    inline_text: Optional[str] = None
    prompt: Optional[str] = None
    model: Optional[str] = None
    extras: dict = field(default_factory=dict)


def count_tokens(text: str) -> int:
    if not text:
        return 0
    if _TIKTOKEN_AVAILABLE:
        return len(tiktoken.get_encoding("p50k_base").encode(text))
    return len(text) // 4


def _truncate(text: str) -> str:
    """Truncate text to MAX_MESSAGE_CHARS. If truncated, last 3 chars are '...'."""
    if not text or len(text) <= MAX_MESSAGE_CHARS:
        return text or ""
    keep = max(MAX_MESSAGE_CHARS - 3, 0)
    return text[:keep] + "..."


def _redact(text: str) -> str:
    if not text:
        return ""
    for pattern, replacement in _ALWAYS_REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    if REDACT_ENABLED:
        for pattern, replacement in _OPTIONAL_REDACT_PATTERNS:
            text = pattern.sub(replacement, text)
    return text


def _sanitize(text: Optional[str]) -> str:
    return _truncate(_redact(text or ""))


def _build_part(content: str) -> dict:
    return {"type": "text", "content": _sanitize(content)}


def _message(role: str, content: str, finish_reason: Optional[str] = None) -> dict:
    msg: dict = {"role": role, "parts": [_build_part(content)]}
    if finish_reason:
        msg["finish_reason"] = finish_reason
    return msg


def _trace_path(session_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id) or "unknown"
    return TELEMETRY_DIR / f"ctx-tracing-{safe}.json"


def _load_trace(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_trace(path: Path, data: dict) -> None:
    try:
        TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as exc:
        print(f"[ctx-tracker] trace write failed: {exc}", file=sys.stderr)


def _git_config(key: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "config", "--get", key],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
        )
        value = out.stdout.strip()
        return value or None
    except (OSError, subprocess.SubprocessError):
        return None


# Prices in USD per 1M tokens. Update when Anthropic/OpenAI pricing changes.
_MODEL_PRICING: dict = {
    "claude-opus-4-7":   {"in": 15.00, "out": 75.00, "cache_read": 1.50, "cache_write": 18.75},
    "claude-opus-4-6":   {"in": 15.00, "out": 75.00, "cache_read": 1.50, "cache_write": 18.75},
    "claude-sonnet-4-6": {"in":  3.00, "out": 15.00, "cache_read": 0.30, "cache_write":  3.75},
    "claude-sonnet-4-5": {"in":  3.00, "out": 15.00, "cache_read": 0.30, "cache_write":  3.75},
    "claude-haiku-4-5":  {"in":  1.00, "out":  5.00, "cache_read": 0.10, "cache_write":  1.25},
}


def _price_for(model: Optional[str]) -> Optional[dict]:
    if not model:
        return None
    # Normalize: convert to lowercase and replace spaces/dots with hyphens
    m = model.lower().replace(" ", "-").replace(".", "-")
    for key, rates in _MODEL_PRICING.items():
        if key in m:
            return rates
    return None


def _compute_cost_usd(model: Optional[str], usage: Optional[dict]) -> Optional[float]:
    rates = _price_for(model)
    if not rates or not usage:
        return None
    inp    = usage.get("input_tokens", 0) or 0
    outp   = usage.get("output_tokens", 0) or 0
    c_read = usage.get("cache_read_input_tokens", 0) or 0
    c_new  = usage.get("cache_creation_input_tokens", 0) or 0
    total = (
        inp    * rates["in"] +
        outp   * rates["out"] +
        c_read * rates["cache_read"] +
        c_new  * rates["cache_write"]
    ) / 1_000_000
    return round(total, 6)


def _collect_otel_resource_attrs() -> dict:
    """Parse OTEL_RESOURCE_ATTRIBUTES (comma-separated key=value pairs).

    Standard Claude Code / OTel convention for team and cost-center tagging,
    e.g. OTEL_RESOURCE_ATTRIBUTES=department=engineering,team.id=platform,cost_center=eng-123
    """
    raw = os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
    out: dict = {}
    if not raw:
        return out
    for pair in raw.split(","):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        k, v = k.strip(), v.strip()
        if k:
            out[k] = v
    return out


def _collect_user_info() -> dict:
    """Collect OTel-style identity/host attributes, plus optional team/org tags."""
    info: dict = {}
    try:
        info["user.name"] = os.environ.get("USERNAME") or getpass.getuser()
    except Exception:
        pass
    git_name = _git_config("user.name")
    if git_name:
        info["user.full_name"] = git_name
    if info.get("user.name"):
        info["user.id"] = info["user.name"]
    git_email = _git_config("user.email")
    user_email = os.environ.get("CLAUDE_USER_EMAIL") or git_email
    if user_email:
        info["user.email"] = user_email
    try:
        info["host.name"] = socket.gethostname()
    except OSError:
        pass
    info["os.type"] = platform.system().lower()
    info["os.version"] = platform.release()
    info["host.arch"] = platform.machine()
    term = os.environ.get("TERM_PROGRAM") or os.environ.get("TERM")
    if term:
        info["terminal.type"] = term
    app_version = os.environ.get("CLAUDE_CODE_VERSION")
    if app_version:
        info["app.version"] = app_version
    info.update(_collect_otel_resource_attrs())
    return info


def _load_system_instructions() -> list[dict]:
    """Snapshot repo-local system prompt sources (CLAUDE.md, .windsurfrules)."""
    sources = [_REPO_ROOT / "CLAUDE.md", _REPO_ROOT / ".windsurfrules"]
    out: list[dict] = []
    for src in sources:
        if src.exists():
            try:
                out.append(_build_part(src.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return out


def _parse_transcript(
    path: str,
) -> tuple[str, Optional[str], Optional[dict], Optional[str], Optional[dict], Optional[str]]:
    """
    Walk a JSONL transcript. Supports both Claude API format and Windsurf format.

    Returns: (full_text, latest_model, latest_assistant_message,
              latest_response_id, latest_usage, latest_request_id)
    """
    if not path or not os.path.exists(path):
        return "", None, None, None, None, None
    parts: list[str] = []
    latest_model: Optional[str] = None
    latest_assistant: Optional[dict] = None
    latest_response_id: Optional[str] = None
    latest_usage: Optional[dict] = None
    latest_request_id: Optional[str] = None
    is_windsurf_format = False

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            
            if not isinstance(entry, dict):
                continue
            
            # Detect Windsurf format by checking for 'type' field
            entry_type = entry.get("type")
            if entry_type in ("user_input", "planner_response", "view_file", "run_command", "grep_search", "find", "code_action", "todo_list"):
                is_windsurf_format = True
                
                # Extract user input
                if entry_type == "user_input":
                    user_response = entry.get("user_input", {}).get("user_response", "")
                    if user_response:
                        parts.append(user_response)
                
                # Extract planner response (assistant message)
                elif entry_type == "planner_response":
                    response = entry.get("planner_response", {}).get("response", "")
                    if response:
                        parts.append(response)
                        latest_assistant = _message("assistant", response)
                
                continue
            
            # Claude API format parsing (original logic)
            if entry.get("requestId"):
                latest_request_id = entry["requestId"]
            msg = entry.get("message", entry)
            if not isinstance(msg, dict):
                continue
            if msg.get("model"):
                latest_model = msg["model"]
            if msg.get("id"):
                latest_response_id = msg["id"]
            if isinstance(msg.get("usage"), dict):
                latest_usage = msg["usage"]

            role = msg.get("role")
            content = msg.get("content")
            text_chunks: list[str] = []
            if isinstance(content, str):
                text_chunks.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_chunks.append(block.get("text", ""))
            joined = "\n".join(text_chunks)
            if joined:
                parts.append(joined)
            if role == "assistant" and joined:
                latest_assistant = _message(
                    "assistant", joined, msg.get("stop_reason") or msg.get("finish_reason")
                )
    
    # For Windsurf format, create synthetic usage data from token counts
    full_text = "\n".join(parts)
    if is_windsurf_format and full_text and not latest_usage:
        # Estimate tokens from the full conversation text
        total_tokens = count_tokens(full_text)
        # Rough split: assume last message is output, rest is input
        if latest_assistant:
            assistant_text = latest_assistant.get("parts", [{}])[0].get("content", "")
            output_tokens = count_tokens(assistant_text)
            input_tokens = max(total_tokens - output_tokens, 0)
        else:
            input_tokens = total_tokens
            output_tokens = 0
        
        latest_usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
    
    return (
        full_text,
        latest_model,
        latest_assistant,
        latest_response_id,
        latest_usage,
        latest_request_id,
    )


def _provider_name(ide: str) -> str:
    override = os.environ.get("GEN_AI_PROVIDER_NAME")
    if override:
        return override
    return {"claude-code": "anthropic", "copilot": "openai", "windsurf": "unknown"}.get(
        ide, "unknown"
    )


def _new_trace(event: HookEvent, model: Optional[str]) -> dict:
    return {
        "schema_url": OTEL_SCHEMA_URL,
        "resource": {
            "service.name": "propeliq.ctx-tracker",
            "gen_ai.framework": event.ide,
            **_collect_user_info(),
        },
        "gen_ai.conversation.id": event.session_id,
        "gen_ai.provider.name": _provider_name(event.ide),
        "gen_ai.operation.name": "chat",
        "gen_ai.request.model": model,
        "gen_ai.system_instructions": _load_system_instructions(),
        "context_window": {
            "limit_tokens": _resolve_context_limit(model),
            "counting_method": "tiktoken" if _TIKTOKEN_AVAILABLE else "estimated",
        },
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "_cumulative_input_tokens": 0,
        "turns": [],
    }


def _open_turn_index(trace: dict) -> Optional[int]:
    for i in range(len(trace.get("turns", [])) - 1, -1, -1):
        if "end_time" not in trace["turns"][i]:
            return i
    return None


def dispatch(event: HookEvent) -> None:
    """Handle a normalised hook event. Updates the per-session trace file."""
    now = datetime.now().isoformat(timespec="seconds")
    path = _trace_path(event.session_id)
    trace = _load_trace(path)

    (
        full_text,
        scanned_model,
        latest_assistant,
        response_id,
        usage,
        request_id,
    ) = _parse_transcript(event.transcript_path or "")
    model = event.model or scanned_model or trace.get("gen_ai.request.model")

    if not trace:
        trace = _new_trace(event, model)
    if model and not trace.get("gen_ai.request.model"):
        trace["gen_ai.request.model"] = model
    cw = trace.setdefault("context_window", {})
    cw["limit_tokens"] = _resolve_context_limit(model)
    trace["updated_at"] = now

    if event.phase == PHASE_PRE:
        # Input tokens for this turn. Claude/Windsurf transcripts at PRE time
        # hold everything up to and including the new user message; Copilot
        # has no transcript so we count the prompt text and accumulate.
        
        # Diagnostic: warn if prompt is empty
        if not (event.prompt or event.inline_text) and event.ide != "copilot":
            print(f"[ctx-tracker] WARNING: Empty prompt in PRE phase for {event.ide}", file=sys.stderr)
            print(f"[ctx-tracker] session_id={event.session_id}, model={event.model}", file=sys.stderr)
        
        if event.ide == "copilot":
            prompt_tokens = count_tokens(event.prompt or event.inline_text or "")
            input_tokens = trace.get("_cumulative_input_tokens", 0) + prompt_tokens
        else:
            input_tokens = count_tokens(full_text) if full_text else count_tokens(event.prompt or "")
        trace["_cumulative_input_tokens"] = input_tokens

        turn: dict = {
            "turn_id": len(trace["turns"]) + 1,
            "event.name": "gen_ai.client.inference.operation.details",
            "start_time": now,
            "gen_ai.operation.name": "chat",
            "gen_ai.input.messages": [_message("user", event.prompt or event.inline_text or "")],
            "gen_ai.usage.input_tokens": input_tokens,
        }
        if model:
            turn["gen_ai.request.model"] = model
        trace["turns"].append(turn)
        _save_trace(path, trace)
        return

    # POST phase: close the latest open turn.
    idx = _open_turn_index(trace)
    if idx is None:
        trace["turns"].append({
            "turn_id": len(trace["turns"]) + 1,
            "event.name": "gen_ai.client.inference.operation.details",
            "start_time": now,
            "gen_ai.operation.name": "chat",
            "gen_ai.input.messages": [],
            "gen_ai.usage.input_tokens": trace.get("_cumulative_input_tokens", 0),
        })
        idx = len(trace["turns"]) - 1
    turn = trace["turns"][idx]

    pre_total = trace.get("_cumulative_input_tokens", 0)
    if full_text:
        post_total = count_tokens(full_text)
    elif event.inline_text:
        post_total = pre_total + count_tokens(event.inline_text)
    else:
        post_total = pre_total
    output_tokens = max(post_total - pre_total, 0)

    if latest_assistant is None and event.inline_text:
        latest_assistant = _message("assistant", event.inline_text)

    turn["end_time"] = now
    try:
        start = datetime.fromisoformat(turn["start_time"])
        elapsed = (datetime.fromisoformat(now) - start).total_seconds()
        turn["duration_seconds"] = round(elapsed, 3)
        turn["duration_ms"] = int(round(elapsed * 1000))
        turn["gen_ai.server.time_to_complete"] = round(elapsed, 3)
    except ValueError:
        pass
    if model:
        turn["gen_ai.response.model"] = model
    if response_id:
        turn["gen_ai.response.id"] = response_id
    if request_id:
        turn["gen_ai.request.id"] = request_id
    turn["gen_ai.output.messages"] = [latest_assistant] if latest_assistant else []
    turn["gen_ai.usage.output_tokens"] = output_tokens

    if usage:
        turn["gen_ai.usage.cache_read_tokens"] = usage.get("cache_read_input_tokens", 0) or 0
        turn["gen_ai.usage.cache_creation_tokens"] = usage.get("cache_creation_input_tokens", 0) or 0
        # Prefer the API's authoritative input_tokens (includes system prompt, tools, MCP context)
        # over the tiktoken-estimated user-message-only count from PRE phase.
        if isinstance(usage.get("input_tokens"), int):
            turn["gen_ai.usage.input_tokens"] = usage["input_tokens"]
        if isinstance(usage.get("output_tokens"), int):
            turn["gen_ai.usage.output_tokens"] = usage["output_tokens"]
    cost = _compute_cost_usd(model, usage)
    if cost is not None:
        turn["gen_ai.usage.cost_usd"] = cost
        trace["gen_ai.usage.cost_usd_total"] = round(
            trace.get("gen_ai.usage.cost_usd_total", 0.0) + cost, 6
        )

    context_limit = _resolve_context_limit(model)
    turn["context_window.percentage_used"] = (
        round(post_total / context_limit * 100, 2) if context_limit else 0.0
    )
    turn["context_window.remaining_tokens"] = max(context_limit - post_total, 0)

    # Roll cumulative forward so the next turn's input tokens start from here.
    trace["_cumulative_input_tokens"] = post_total
    _save_trace(path, trace)

    print(
        f"[{event.ide}] turn={turn['turn_id']} session={event.session_id} "
        f"in={pre_total:,} out={output_tokens:,} total={post_total:,} "
        f"({turn['context_window.percentage_used']}% used)",
        file=sys.stderr,
    )


def read_stdin_json() -> dict:
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}
