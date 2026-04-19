"""Per-run console mirror.

Creates a log file at logs/run-<timestamp>.log and duplicates every Rich
Console write into it. The terminal keeps colors; the log file strips ANSI
codes so it's grep-friendly.

Separate from events.jsonl:
- events.jsonl is the STRUCTURED event log (greppable with jq)
- logs/run-*.log is the HUMAN-READABLE transcript of what you saw in your terminal

Both persist even on crash — the file is line-buffered and flushed on every write.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path
from typing import IO, TextIO, cast

from rich.console import Console

# Matches CSI / OSC / SGR escape sequences
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


class _Tee:
    """File-like that writes to stdout (with ANSI) AND a log file (without ANSI)."""

    def __init__(self, terminal: TextIO, log_file: TextIO) -> None:
        self.terminal = terminal
        self.log_file = log_file

    def write(self, data: str) -> int:
        self.terminal.write(data)
        self.terminal.flush()
        self.log_file.write(_strip_ansi(data))
        self.log_file.flush()
        return len(data)

    def flush(self) -> None:
        self.terminal.flush()
        self.log_file.flush()

    def isatty(self) -> bool:
        # Lie to Rich so it still emits colors for the terminal side
        return self.terminal.isatty()

    def fileno(self) -> int:
        return self.terminal.fileno()


def setup_run_log(log_dir: Path = Path("logs")) -> tuple[Console, Path, TextIOWrapper]:
    """Create a log file and a tee'd Console.

    Returns (console, log_path, log_file_handle).
    Caller should close log_file_handle at end of run.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"run-{ts}.log"

    # Line-buffered so crashes preserve most of the log
    log_file = log_path.open("w", buffering=1, encoding="utf-8")

    tee = _Tee(sys.stdout, log_file)
    # `_Tee` duck-types as IO[str] at runtime (has write/flush/isatty).
    # Cast tells the type checker explicitly.
    console = Console(file=cast(IO[str], tee), force_terminal=True)

    # Header so the file self-identifies
    header = (
        f"# run-{ts}\n"
        f"# started: {datetime.now().isoformat(timespec='seconds')}\n"
        f"# cwd: {Path.cwd()}\n"
        f"# ─────────────────────────────────────────────\n"
    )
    log_file.write(header)
    log_file.flush()

    return console, log_path, log_file
