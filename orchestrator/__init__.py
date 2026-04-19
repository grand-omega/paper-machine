"""new-paper-machine orchestrator.

Rides on Claude Code (`claude -p --resume`) for persistent agent sessions.
Owns: multi-agent pipeline, SQLite state, budget tracking, reset policy.
"""
