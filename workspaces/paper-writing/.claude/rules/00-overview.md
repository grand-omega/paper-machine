# Project overview

This pipeline produces research papers autonomously. The user provides a research direction in `foothold.md` and relevant papers in `related_works/`. Agents then:

1. Review the literature and summarize the state of the art
2. Propose a small set of concrete experiments that advance the foothold
3. Run experiments, recording results and lessons
4. Draft a paper
5. Review the paper; revise until quality criteria are met

## Canonical state

- **Experiments, lessons, results:** `state/experiments.sqlite` (structured, schema-validated)
- **Agent conversations:** `~/.claude/projects/<cwd-hash>/<uuid>.jsonl` (managed by Claude Code)
- **Session UUID pointers:** `.agent_state/<role>.session`
- **The research scope:** `foothold.md` (never edited by agents)

Do **not** use markdown files as shared mutable state. Markdown is for human-readable input (foothold, rules, paper drafts) — not for cross-agent communication.

## What "done" looks like

- Each proposed experiment has a status in SQLite: `pending`, `running`, `completed`, `failed`
- Completed experiments have numerical results + a short natural-language summary
- The final `paper/main.tex` compiles cleanly and passes the reviewer's checklist
- Lessons learned are appended to SQLite for future rounds

## Collaboration boundaries

You are one agent of several. Do not assume you can see other agents' conversations — you can only see what they've committed to SQLite or written to shared files (paper drafts, figures, etc.). If you need information from another agent, surface it to the orchestrator.
