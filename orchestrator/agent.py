"""PersistentAgent — a role that keeps its conversation across subprocess invocations.

Uses `claude -p --session-id <uuid>` to create, then `--resume <uuid>` to continue.
Session transcript lives at ~/.claude/projects/<cwd-hash>/<uuid>.jsonl (managed by Claude Code).
We only track the UUID in .agent_state/<name>.session.
"""

from __future__ import annotations

import asyncio
import json
import uuid as uuid_mod
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator


@dataclass
class PersistentAgent:
    """One role = one UUID = one long-lived conversation."""

    name: str
    allowed_tools: list[str]
    model: str = "opus"
    state_dir: Path = field(default_factory=lambda: Path(".agent_state"))
    extra_claude_args: list[str] = field(default_factory=list)

    # Runtime
    _session_id: str | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def session_file(self) -> Path:
        return self.state_dir / f"{self.name}.session"

    # -------- Session lifecycle --------

    def _load_session_id(self) -> str | None:
        if self.session_file.exists():
            sid = self.session_file.read_text().strip()
            return sid or None
        return None

    def _save_session_id(self, sid: str) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.session_file.write_text(sid)

    async def hard_reset(self) -> None:
        """Nuke the session pointer. Next send() creates a fresh session."""
        if self.session_file.exists():
            self.session_file.unlink()
        self._session_id = None

    async def soft_reset(self) -> AsyncIterator[dict]:
        """Invoke /compact with an agent-specific directive.
        Keeps skills, drops noise. Still counts as one turn.
        """
        directive = (
            "/compact\n"
            "Preserve: accumulated skills, successful patterns, reference paths, "
            "facts learned. Drop: failed attempts, raw tool output, dead ends."
        )
        async for ev in self.send(directive):
            yield ev

    # -------- Main send loop --------

    async def send(self, instruction: str, *, system_prompt: str | None = None) -> AsyncIterator[dict]:
        """Send an instruction to this agent. Yields parsed JSON events from stream-json output.

        On first call, creates a session (session_id generated). Subsequent calls resume.
        """
        async with self._lock:
            sid = self._session_id or self._load_session_id()
            is_new = sid is None

            if sid is None:
                sid = str(uuid_mod.uuid4())
                self._save_session_id(sid)

            self._session_id = sid
            cmd = self._build_cmd(
                resume=not is_new,
                session_id=sid,
                system_prompt=system_prompt if is_new else None,
            )

            async for event in self._run_subprocess(cmd, instruction):
                yield event

    # -------- Subprocess plumbing --------

    def _build_cmd(self, *, resume: bool, session_id: str, system_prompt: str | None) -> list[str]:
        cmd: list[str] = [
            "claude",
            "-p",
            "-",                                      # read prompt from stdin
            "--model", self.model,
            "--allowedTools", ",".join(self.allowed_tools),
            "--output-format", "stream-json",
            "--verbose",                              # include tool_use events
        ]
        if resume:
            cmd.extend(["--resume", session_id])
        else:
            cmd.extend(["--session-id", session_id])
            if system_prompt:
                cmd.extend(["--append-system-prompt", system_prompt])

        cmd.extend(self.extra_claude_args)
        return cmd

    async def _run_subprocess(self, cmd: list[str], instruction: str) -> AsyncIterator[dict]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None

        # Send instruction via stdin
        proc.stdin.write(instruction.encode())
        await proc.stdin.drain()
        proc.stdin.close()

        # Stream stdout line-by-line as JSON events
        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode().strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"type": "raw", "line": line}
            yield event

        rc = await proc.wait()
        if rc != 0:
            stderr_bytes = await proc.stderr.read() if proc.stderr else b""
            yield {
                "type": "subprocess_error",
                "returncode": rc,
                "stderr": stderr_bytes.decode(errors="replace"),
            }
