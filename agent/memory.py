"""Lightweight persistent memory for chat mode.

Chat sessions (agent/sdk_core.py) are otherwise stateless across runs: exit
the process and everything discussed is gone. This module gives chat mode a
single local JSON file to read at the start of a session and write at the
end, so a short plain-text summary of what happened carries forward into the
next session.

This is infrastructure the agent's own code reads/writes around the
conversation — not a tool Claude calls, and Claude never sees this file
directly.
"""

import json
from datetime import datetime
from pathlib import Path

MEMORY_FILE = Path(__file__).resolve().parent.parent / "memory.json"


def load_memory() -> str:
    """Return the saved summary text, or "" if there's no memory yet."""
    if not MEMORY_FILE.exists():
        return ""
    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    return data.get("summary", "")


def save_memory(summary: str) -> None:
    """Overwrite the saved summary with `summary`."""
    data = {
        "summary": summary,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    MEMORY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
