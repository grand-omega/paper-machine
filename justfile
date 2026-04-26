# paper-machine — top-level dispatcher
#
# Each research workspace lives under workspaces/<name>/ with its own
# .claude/, pyproject.toml, .venv, and justfile. This top-level justfile
# just forwards to the right workspace.
#
# Direct usage also works: `cd workspaces/paper-writing && just run`.

set shell := ["bash", "-uc"]

# default: show available workspaces and top-level recipes
default:
    @just --list
    @echo ""
    @echo "Workspaces:"
    @just workspaces

# list research workspaces
workspaces:
    @for d in workspaces/*/; do \
        [ -d "$d" ] || continue; \
        name=$(basename "$d"); \
        has_foothold=$([ -f "$d/foothold.md" ] && echo "✓" || echo "✗"); \
        has_venv=$([ -d "$d/.venv" ] && echo "✓" || echo "✗"); \
        printf "  %-24s  foothold=%s venv=%s\n" "$name" "$has_foothold" "$has_venv"; \
    done

# run a workspace's pipeline: `just run paper-writing`
run WORKSPACE *ARGS:
    @cd workspaces/{{WORKSPACE}} && just run {{ARGS}}

# run N rounds in a workspace: `just run-rounds paper-writing 3`
run-rounds WORKSPACE N:
    @cd workspaces/{{WORKSPACE}} && just run-rounds {{N}}

# archive a workspace's current run: `just archive paper-writing gemm-baseline`
archive WORKSPACE LABEL="":
    @cd workspaces/{{WORKSPACE}} && just archive {{LABEL}}

# list archives in a workspace
archives WORKSPACE:
    @cd workspaces/{{WORKSPACE}} && just archives

# dump experiment state for a workspace
experiments WORKSPACE:
    @cd workspaces/{{WORKSPACE}} && just experiments

# clean a workspace's runtime state
clean WORKSPACE:
    @cd workspaces/{{WORKSPACE}} && just clean

# reset one agent's memory in a workspace: `just reset-agent paper-writing coder`
reset-agent WORKSPACE NAME:
    @cd workspaces/{{WORKSPACE}} && just reset-agent {{NAME}}

# sync all deps: framework at root, then each workspace
sync:
    @echo "→ syncing framework..." && uv sync
    @for d in workspaces/*/; do \
        [ -d "$d" ] || continue; \
        echo "→ syncing workspace $(basename "$d")..."; \
        (cd "$d" && uv sync); \
    done
