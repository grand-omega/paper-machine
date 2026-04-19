"""Structured event logger.

Every interesting thing that happens — turn_start, tool_call, retry, compact,
budget-exhaustion, reset — gets one JSONL line written to events.jsonl.
Greppable, tail-able, trivially importable into a notebook for analysis.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

EVENTS_PATH = Path("events.jsonl")


def emit(event_type: str, **data: object) -> None:
    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "event": event_type,
        **data,
    }
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
