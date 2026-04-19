# new-paper-machine — common commands

set shell := ["bash", "-uc"]

# show available recipes
default:
    @just --list

# one-time setup
setup:
    uv sync
    @echo "✓ Deps installed. Now: claude /login (once), then 'just run'"

# run a single round of the pipeline
run:
    uv run python -m orchestrator.orchestrate --rounds 1

# run N rounds
run-rounds N:
    uv run python -m orchestrator.orchestrate --rounds {{N}}

# dump all experiments as JSON
experiments:
    uv run python -m orchestrator.state --dump

# hard-reset a specific agent (wipes its session UUID; next call starts fresh)
reset-agent NAME:
    rm -f .agent_state/{{NAME}}.session
    @echo "✓ Reset {{NAME}}."

# nuke all runtime state (sessions, DB, results). Keeps .claude/ and foothold.md.
clean:
    rm -rf state/ .agent_state/ agent_results/ events.jsonl
    @echo "✓ Clean."
