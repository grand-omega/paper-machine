# new-paper-machine — common commands

set shell := ["bash", "-uc"]

# show available recipes
default:
    @just --list

# one-time setup (Python deps only)
setup:
    uv sync
    @echo "✓ Python deps installed."
    @echo "  Next: 'just setup-latex' (if basictex), then 'claude /login', then 'just run'"

# one-time: install LaTeX packages the paper-writer commonly needs (basictex users only)
# Requires sudo. If you have mactex-no-gui, you already have everything.
# Note: tabularx, array, multicol etc. ship bundled in basictex under the `tools` package
# and don't need to be named here.
setup-latex:
    @echo "Installing common LaTeX packages via tlmgr (requires sudo)..."
    sudo /Library/TeX/texbin/tlmgr update --self
    sudo /Library/TeX/texbin/tlmgr install \
        booktabs caption siunitx microtype \
        titling titlesec enumitem \
        pgfplots biblatex biber \
        csquotes multirow \
        xcolor etoolbox
    @just verify-latex

# verify all expected LaTeX packages are findable via kpsewhich
verify-latex:
    @export PATH="/Library/TeX/texbin:$PATH" && \
    missing=0; \
    for pkg in booktabs caption siunitx microtype titling titlesec enumitem pgfplots biblatex csquotes multirow tabularx xcolor etoolbox; do \
        if ! kpsewhich $pkg.sty > /dev/null 2>&1; then \
            echo "✗ $pkg  ← missing"; \
            missing=$((missing + 1)); \
        fi; \
    done; \
    if [ $missing -eq 0 ]; then \
        echo "✓ All expected LaTeX packages present."; \
    else \
        echo "⚠ $missing package(s) missing — install with 'sudo tlmgr install <name>'"; \
        exit 1; \
    fi

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

# nuke generated outputs inside the project root for a fresh run.
# Principle: `clean` NEVER reaches outside the project dir.
# Keeps: .claude/ config, orchestrator/ code, foothold.md, related_works/, uv.lock, .venv
# Removes: SQLite state, agent UUIDs, experiments/, paper/, logs, caches
#
# Note: Claude Code session transcripts live at
#   ~/.claude/projects/-Users-yanwenxu-Desktop-new-paper-machine/*.jsonl
# These become orphaned (nothing points to them) after `clean` but take disk
# space. Delete manually if you care: `rm -rf ~/.claude/projects/<path-slug>`.
# Since .agent_state/ is wiped, the next run creates fresh session UUIDs —
# orphaned transcripts don't affect behavior, just occupy disk.
clean:
    @echo "Removing runtime state..."
    rm -rf state/ .agent_state/ agent_results/ events.jsonl logs/
    @echo "Removing generated paper + experiment scripts..."
    rm -rf paper/ experiments/
    @echo "Removing Python + linter caches..."
    rm -rf orchestrator/__pycache__/ .ruff_cache/
    @echo "✓ Clean (project-root only — orphaned Claude Code transcripts in ~/.claude/projects/ remain)."

# same as `clean` but keeps paper/ and experiments/ (for comparing output across runs)
clean-soft:
    rm -rf state/ .agent_state/ agent_results/ events.jsonl logs/
    rm -rf orchestrator/__pycache__/ .ruff_cache/
    @echo "✓ Clean (kept paper/ and experiments/ for reference)."

# tail the latest run log (follows as it's written)
tail-log:
    @tail -f $(ls -t logs/run-*.log | head -1)

# show the latest run log (from the top)
last-log:
    @less -R $(ls -t logs/run-*.log | head -1)
