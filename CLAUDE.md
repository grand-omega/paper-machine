# new-paper-machine — project-wide context

This repo is an autonomous research-paper pipeline. Multiple role-specialized agents (literature-reviewer, experimenter, paper-writer, reviewer) collaborate under a Python orchestrator.

## What you (the agent) are part of

You are one of several persistent agents. Your conversation persists across Python-orchestrator invocations via `claude -p --resume <uuid>`. Each agent role has its own UUID stored in `.agent_state/`.

Other agents share structured state via `state/experiments.sqlite`. They do **not** read your conversation; they see only the results you commit to the database.

## Hard rules

- Your working directory is the project root. Use **absolute paths** where possible.
- The research scope is defined in `foothold.md`. Respect it.
- Project-wide conventions are in `.claude/rules/*.md`. Path-conditional rules load automatically based on files you're touching.
- Do **not** edit `foothold.md`, `.claude/`, `orchestrator/`, or `state/` unless explicitly asked.
- Permissions are code-enforced via `.claude/settings.json`. If a tool is blocked, don't try to work around it — surface it to the orchestrator.

## Working with shared state

Canonical state lives in SQLite (`state/experiments.sqlite`), not markdown files. Use the provided skills or the orchestrator's SQL helpers. If you need to read/write experiment rows, invoke the `run-experiment` skill (`/skills` → `run-experiment`), which wraps the SQL.

## Communicating back to the user

- Be terse. The orchestrator already logs events; don't narrate routine actions.
- Flag genuine uncertainty or blockers. Don't pretend work was verified when it wasn't.
- File references use `path:line` format so the user can click them.

## When things fail

- Build error in an experiment → try up to 3 fixes, then record the failure in SQLite with the error excerpt. Don't loop forever.
- Missing dependency → check `pyproject.toml` first, then surface to the user rather than installing unprompted.
- Contradictory instruction → raise it in your final response, don't silently pick one.
