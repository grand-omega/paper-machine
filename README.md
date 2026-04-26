# AGN Paper Machine

Autonomous research-paper pipeline built on **Claude Code** as the runtime.

Given a research direction (`foothold.md`), the pipeline runs a team of persistent, role-specialized agents that review literature, propose experiments, run them, write a paper, and revise.

## Design philosophy

**Don't build a framework — orchestrate Claude Code.** This project contributes:

- **Roles** via `.claude/agents/*.md`
- **Memory** via `.claude/rules/*.md` (path-conditional where useful)
- **Reusable procedures** via `.claude/skills/`
- **Code-enforced permissions** via `.claude/settings.json`
- **Python orchestration** (~300 lines) that drives persistent agent sessions via `claude -p --resume`

Everything else — the ReAct loop, tools, retries, compaction, streaming, prompt caching, OAuth auth — is inherited from Claude Code. Your $200 Max subscription covers all model usage.

## Architecture at a glance

```
Python orchestrator (orchestrator/)
       │ per turn
       ▼
claude -p --resume <uuid>   ← one subprocess per agent turn
       │
       ▼
~/.claude/projects/<hash>/<uuid>.jsonl   ← persistent conversation, auto-loaded
```

Each role (literature-reviewer, experimenter, paper-writer, reviewer) has its own UUID, own system prompt, own tool allowlist, own accumulated memory.

## Directory layout

```
new-paper-machine/
├── .claude/
│   ├── CLAUDE.md                          ← cross-cutting project facts (auto-injected)
│   ├── settings.json                      ← permissions, hooks
│   ├── rules/                             ← memory split by topic
│   │   ├── 00-overview.md                 ← always loaded
│   │   ├── 10-experiment-protocol.md      ← always loaded
│   │   ├── 20-paper-protocol.md           ← always loaded
│   │   ├── python/conventions.md          ← path-conditional: **/*.py
│   │   └── latex/style.md                 ← path-conditional: **/*.tex
│   ├── agents/                            ← role subagent definitions
│   │   ├── literature-reviewer.md
│   │   ├── experimenter.md
│   │   ├── paper-writer.md
│   │   └── reviewer.md
│   └── skills/
│       ├── run-experiment/SKILL.md        ← reproducible experiment protocol
│       └── compile-latex/SKILL.md         ← LaTeX build + error extraction
│
├── orchestrator/
│   ├── __init__.py
│   ├── agent.py                           ← PersistentAgent class
│   ├── budget.py                          ← 5-hour message-window tracker
│   ├── state.py                           ← SQLite experiment store (+ CLI)
│   ├── events.py                          ← JSONL structured event log
│   └── orchestrate.py                     ← main pipeline
│
├── foothold.md                            ← YOUR research direction (edit this)
├── pyproject.toml                          ← minimal deps (just `rich`)
├── justfile                                ← common commands
└── README.md

# Created at runtime (gitignored):
#   state/experiments.sqlite
#   .agent_state/<role>.session
#   agent_results/<exp-id>/
#   events.jsonl
#
# Created by you:
#   related_works/                         ← drop PDFs here for literature-reviewer
```

## Prerequisites

- **Claude Code CLI** logged in with your Max subscription: `claude /login` (one-time)
- **Python 3.11+** and `uv` (or `pip`)
- **`just`** command runner (`brew install just`)

## Quickstart

```bash
# 1. Install the one Python dep (rich)
uv sync

# 2. Edit foothold.md with your research direction
$EDITOR foothold.md

# 3. Optional: drop any related papers into related_works/
mkdir -p related_works && cp ~/Downloads/*.pdf related_works/

# 4. Run
just run                                    # single round
just run-rounds 3                           # three rounds
```

## How sessions persist

Each agent role gets a stable UUID stored in `.agent_state/<role>.session`. On the first invocation, `orchestrate.py` creates the session with `--session-id <uuid>`. Every subsequent call uses `--resume <uuid>`, which makes Claude Code re-load the full prior conversation automatically.

Result: the experimenter agent remembers what it tried in experiment 3 when it starts experiment 4. No re-injection of markdown state.

## Reset policy (who keeps memory vs gets fresh eyes)

| Role | Policy | Why |
|---|---|---|
| `literature-reviewer` | 🔥 keep across runs | Accumulated paper knowledge is valuable |
| `experimenter` | 🔥 hot across experiments; soft-reset between rounds | Skills compound; between rounds, drop noise |
| `paper-writer` | 🔥 keep through drafts | Needs to remember what it wrote |
| `reviewer` | ❄️ hard-reset every draft | Fresh eyes on each revision |

Configured in `orchestrator/orchestrate.py` — `RESET_POLICY` dict.

## Customizing for your project

1. **Edit `foothold.md`** — your research question, hypothesis, constraints
2. **Drop papers into `related_works/`** — the literature-reviewer reads them
3. **Edit `.claude/rules/00-overview.md`** — project-wide facts
4. **Optionally tune `.claude/agents/*.md`** — adjust role behaviors
5. **Run**

Only the foothold and rules should need editing per project. The orchestrator and role definitions are reusable.

## What this replaces (vs. naive approach)

- ❌ `subprocess.run([claude, -p, ...])` with markdown state re-injection every turn
- ❌ Parsing markdown tables as canonical state
- ❌ Prose-only file isolation ("please don't write outside your directory")
- ❌ Hardcoded context windowing (`last 20 experiments`)
- ❌ Custom retry / compaction / tool systems

All solved by riding on Claude Code + persistent sessions + SQLite + `.claude/settings.json` permissions.

## License

UNLICENSED — personal project.
