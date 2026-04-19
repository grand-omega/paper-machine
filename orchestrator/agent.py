"""PersistentAgent — a role that keeps its conversation across subprocess invocations.

Uses `claude -p --session-id <uuid>` to create, then `--resume <uuid>` to continue.
Session transcript lives at ~/.claude/projects/<cwd-hash>/<uuid>.jsonl (managed by Claude Code).
We only track the UUID in .agent_state/<name>.session.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid as uuid_mod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator


# ──────────────────────────────────────────────────────────────────────────────
# Frontmatter parser — loads role config from .claude/agents/<name>.md
# ──────────────────────────────────────────────────────────────────────────────
#
# Our frontmatter is simple YAML: scalar key:value pairs + optional single-line
# lists like `tools: [Read, Write, Bash]`. We avoid pulling pyyaml as a dep for
# this small surface. If frontmatter grows more complex (multi-line lists,
# nested objects), swap to `pyyaml` in `uv add pyyaml`.

def _parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Parse YAML-ish frontmatter + markdown body from `path`.

    Returns (frontmatter_dict, body_string). Empty frontmatter if the file
    doesn't start with ``---``. Raises FileNotFoundError if path missing.
    """
    text = path.read_text()
    if not text.startswith("---\n"):
        return {}, text.strip()

    # Split off the opening fence, then find the closing one.
    _, rest = text.split("---\n", 1)
    if "\n---\n" not in rest:
        # malformed — treat entire file as body
        return {}, text.strip()
    fm_text, _, body = rest.partition("\n---\n")

    frontmatter: dict[str, Any] = {}
    for raw_line in fm_text.strip().split("\n"):
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            # single-line list: [a, b, c] or ["a", "b"]
            items = [
                item.strip().strip("\"'")
                for item in value[1:-1].split(",")
                if item.strip()
            ]
            frontmatter[key] = items
        else:
            frontmatter[key] = value.strip("\"'")

    return frontmatter, body.strip()

# macOS TeX Live (basictex / mactex) installs to a path that isn't on the default
# subprocess PATH. Prepend it so `pdflatex`/`bibtex`/`tlmgr` resolve without the
# agent having to `export PATH=...` on every bash call.
_EXTRA_PATHS = ("/Library/TeX/texbin",)


def _child_env() -> dict[str, str]:
    """Env for claude subprocesses — inherits current env + prepends known tool paths."""
    env = os.environ.copy()
    existing = env.get("PATH", "")
    to_add = [p for p in _EXTRA_PATHS if Path(p).exists() and p not in existing]
    if to_add:
        env["PATH"] = ":".join(to_add) + (":" + existing if existing else "")
    return env


@dataclass
class PersistentAgent:
    """One role = one UUID = one long-lived conversation.

    Prefer `PersistentAgent.from_markdown(name)` so role config stays in
    `.claude/agents/<name>.md` as the single source of truth.
    """

    name: str
    allowed_tools: list[str]
    model: str
    system_prompt: str                           # role prompt body from .claude/agents/<name>.md
    state_dir: Path = field(default_factory=lambda: Path(".agent_state"))
    extra_claude_args: list[str] = field(default_factory=list)

    # Runtime
    _session_id: str | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ── Factory ─────────────────────────────────────────────────────────

    @classmethod
    def from_markdown(
        cls,
        name: str,
        *,
        project_root: Path = Path("."),
        **overrides: Any,
    ) -> "PersistentAgent":
        """Build from `.claude/agents/<name>.md` — frontmatter + body.

        Frontmatter fields consumed: `name` (defaults to arg), `tools`
        (required list), `model` (defaults to `opus`). Body becomes
        `system_prompt` (injected via `--append-system-prompt` on every turn).

        Any keyword overrides (e.g. `model="sonnet"`) win over frontmatter.
        """
        path = project_root / ".claude" / "agents" / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(
                f"No agent definition at {path}. "
                f"Expected a markdown file with frontmatter (name, tools, model) "
                f"and a body that will become the role's system prompt."
            )

        fm, body = _parse_frontmatter(path)
        if not body:
            raise ValueError(
                f"{path} has no body — the markdown body after the frontmatter "
                f"IS the role prompt. Write what the agent should be."
            )

        tools = fm.get("tools")
        if not isinstance(tools, list) or not tools:
            raise ValueError(
                f"{path} frontmatter must contain a non-empty `tools: [...]` list "
                f"(e.g. `tools: [Read, Write, Bash]`). Got: {tools!r}"
            )

        kwargs: dict[str, Any] = dict(
            name=str(fm.get("name", name)),
            allowed_tools=tools,
            model=str(fm.get("model", "opus")),
            system_prompt=body,
        )
        kwargs.update(overrides)
        return cls(**kwargs)

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
        """Invoke `/compact` with a role-specific focus directive.

        Must be single-line: Claude Code's slash-command parser treats
        everything after `/compact ` on the same line as the `args`.
        Multi-line would drop the directive (compact.ts:52 `args.trim()`).
        """
        directive = (
            "/compact Preserve accumulated skills, successful patterns, "
            "reference paths, and facts learned. "
            "Drop failed attempts, raw tool output, and dead ends."
        )
        async for ev in self.send(directive):
            yield ev

    # -------- Main send loop --------

    async def send(self, instruction: str) -> AsyncIterator[dict]:
        """Send an instruction to this agent. Yields parsed JSON events from stream-json.

        On first call, creates a session (new UUID); subsequent calls resume.
        The role prompt (`self.system_prompt`) is always injected via
        `--append-system-prompt` — Claude Code builds the system prompt fresh
        each invocation so this doesn't accumulate across turns.
        """
        async with self._lock:
            sid = self._session_id or self._load_session_id()
            is_new = sid is None

            if sid is None:
                sid = str(uuid_mod.uuid4())
                self._save_session_id(sid)

            self._session_id = sid
            cmd = self._build_cmd(resume=not is_new, session_id=sid)

            async for event in self._run_subprocess(cmd, instruction):
                yield event

    # -------- Subprocess plumbing --------

    def _build_cmd(self, *, resume: bool, session_id: str) -> list[str]:
        cmd: list[str] = [
            "claude",
            "-p",
            "-",                                      # read prompt from stdin
            "--model", self.model,
            "--allowedTools", ",".join(self.allowed_tools),
            "--output-format", "stream-json",
            "--verbose",                              # include tool_use events
            "--include-partial-messages",             # stream text deltas in real time
        ]
        if resume:
            cmd.extend(["--resume", session_id])
        else:
            cmd.extend(["--session-id", session_id])

        # Inject role prompt every call. Claude Code rebuilds the system prompt
        # per invocation (does NOT accumulate), so passing it on resume is safe
        # and ensures role updates in .claude/agents/<name>.md take effect.
        if self.system_prompt:
            cmd.extend(["--append-system-prompt", self.system_prompt])

        cmd.extend(self.extra_claude_args)
        return cmd

    async def _run_subprocess(self, cmd: list[str], instruction: str) -> AsyncIterator[dict]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_child_env(),
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
