"""Persisted, incremental step ledger for a single agent run.

agent/memory.py captures a lossy, Claude-authored prose summary written once
at the end of a chat *session*. This module instead records each step of a
single run — one turn's worth of tool calls — as it actually happens: which
tool, what input, what result, in what order. If the process crashes mid-run
(e.g. the ProcessError recovery in agent/sdk_core.py), the steps already
recorded survive on disk instead of vanishing with the subprocess.

This is infrastructure the agent's own code reads/writes around a run — not
a tool Claude calls, and Claude never sees this file directly.

A run is one turn: one user message in, one final answer (or failure) out.
In chat mode that means a fresh run per turn, matching the granularity of
the existing per-turn failure recovery in _run_chat_async.

Only the latest run is kept — this is a single overwritten file, like
memory.json, not a growing log. The goal is "did the last run finish, and if
not, where did it stop," not a full audit trail.

set_session_id() additionally records the Claude CLI's own session id for the
run, which is what actually lets a later process resume it (see
ClaudeAgentOptions(resume=...) usage in agent/sdk_core.py) rather than just
report that it stopped. reactivate_run() flips a stored run back to
in_progress so a resumed continuation keeps appending to the same ledger
instead of start_run() blanking it out.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

TASK_STATE_FILE = Path(__file__).resolve().parent.parent / "task_state.json"

_STATUS_IN_PROGRESS = "in_progress"
_STATUS_COMPLETED = "completed"
_STATUS_FAILED = "failed"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load() -> dict[str, Any] | None:
    if not TASK_STATE_FILE.exists():
        return None
    try:
        return json.loads(TASK_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save(data: dict[str, Any]) -> None:
    data["updated_at"] = _now()
    TASK_STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def start_run(task: str) -> None:
    """Begin a new run, overwriting any previous run's record."""
    now = _now()
    _save(
        {
            "task": task,
            "status": _STATUS_IN_PROGRESS,
            "started_at": now,
            "steps": [],
            "final_answer": None,
            "failure_reason": None,
            "session_id": None,
        }
    )


def record_step(tool: str, tool_input: dict, result: str, is_error: bool) -> None:
    """Append one completed tool call to the current run and persist it.

    A no-op if there is no run in progress — a bookkeeping miss here
    shouldn't be able to crash the agent loop it's merely observing.
    """
    data = _load()
    if data is None or data.get("status") != _STATUS_IN_PROGRESS:
        return
    data["steps"].append(
        {
            "index": len(data["steps"]),
            "tool": tool,
            "input": tool_input,
            "result": result,
            "is_error": is_error,
            "recorded_at": _now(),
        }
    )
    _save(data)


def set_session_id(session_id: str) -> None:
    """Record the underlying Claude CLI session id for the current run.

    The SDK returns this on every ResultMessage (success or error). Persisting
    it is what makes a later resume possible: a fresh process can pass it back
    as `ClaudeAgentOptions(resume=session_id)` to reload that exact
    conversation's history from the CLI's own on-disk transcript, rather than
    starting a blind new session. A no-op if there is no run recorded.
    """
    data = _load()
    if data is None:
        return
    data["session_id"] = session_id
    _save(data)


def complete_run(final_answer: str) -> None:
    """Mark the current run completed, with its final answer."""
    data = _load()
    if data is None:
        return
    data["status"] = _STATUS_COMPLETED
    data["final_answer"] = final_answer
    _save(data)


def fail_run(reason: str) -> None:
    """Mark the current run failed. Steps already recorded are left as-is."""
    data = _load()
    if data is None:
        return
    data["status"] = _STATUS_FAILED
    data["failure_reason"] = reason
    _save(data)


def reactivate_run() -> dict[str, Any] | None:
    """Flip a stored in_progress/failed run back to in_progress so a resumed
    continuation appends to the same step ledger (via record_step/set_session_id)
    instead of start_run() overwriting it with a blank one. Returns the
    reactivated run's data, or None if there's nothing on disk to reactivate.
    """
    data = _load()
    if data is None:
        return None
    data["status"] = _STATUS_IN_PROGRESS
    data["failure_reason"] = None
    _save(data)
    return data


def load_incomplete_run() -> dict[str, Any] | None:
    """Return the last run's data if it never reached complete_run — i.e.
    its status is still "in_progress" (the process died before finishing)
    or "failed" — otherwise None. Returns None on a missing or corrupt
    file rather than raising.
    """
    data = _load()
    if data is None:
        return None
    if data.get("status") in (_STATUS_IN_PROGRESS, _STATUS_FAILED):
        return data
    return None
