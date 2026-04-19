"""Subscription-mode budget tracking.

Claude Max subscription isn't token-based — it's rolling 5-hour message windows.
Track messages sent and pause when near the cap.

The ~180 msgs/5h on Opus limit is approximate; Anthropic doesn't publish exactly
and it varies. Conservative defaults are fine; the orchestrator will just sleep
on 429s anyway.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class MessageWindow:
    """Rolling 5-hour message-window tracker."""

    limit_opus_per_5h: int = 180            # conservative; tune based on observed 429s
    limit_sonnet_per_5h: int = 900
    window_seconds: float = 5 * 3600

    # (timestamp_epoch, agent_name, model) tuples
    _log: list[tuple[float, str, str]] = field(default_factory=list)

    def record(self, agent_name: str, model: str) -> None:
        self._log.append((time.time(), agent_name, model))
        self._prune()

    def _prune(self) -> None:
        cutoff = time.time() - self.window_seconds
        self._log = [m for m in self._log if m[0] > cutoff]

    def count(self, model: str | None = None) -> int:
        self._prune()
        if model is None:
            return len(self._log)
        return sum(1 for _, _, m in self._log if m == model)

    def at_limit(self, model: str) -> bool:
        if model.startswith("opus"):
            return self.count(model) >= self.limit_opus_per_5h
        return self.count(model) >= self.limit_sonnet_per_5h

    def wait_until_free(self, model: str) -> float:
        """Seconds until one message falls out of the window for this model."""
        self._prune()
        if not self.at_limit(model):
            return 0.0
        # Find oldest message of this model
        model_msgs = [m for m in self._log if m[2] == model]
        if not model_msgs:
            return 0.0
        oldest = min(model_msgs, key=lambda m: m[0])
        return max(0.0, (oldest[0] + self.window_seconds) - time.time())

    def summary(self) -> str:
        self._prune()
        opus = self.count("opus")
        sonnet = sum(1 for _, _, m in self._log if m.startswith("sonnet"))
        haiku = sum(1 for _, _, m in self._log if m.startswith("haiku"))
        total = len(self._log)
        return (
            f"window msgs: total={total} opus={opus}/{self.limit_opus_per_5h} "
            f"sonnet={sonnet}/{self.limit_sonnet_per_5h} haiku={haiku} "
            f"(5h rolling window)"
        )
