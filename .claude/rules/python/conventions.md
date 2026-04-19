---
paths:
  - "**/*.py"
  - "experiments/**"
  - "orchestrator/**"
---

# Python conventions (loaded when working on Python files)

## Style

- Python 3.11+ features encouraged: `match`, `|` unions, `Self`, structural patterns
- Type hints on all function signatures
- `from __future__ import annotations` at top of every file
- Format with `ruff format`, lint with `ruff check`
- Prefer `pathlib.Path` over `os.path`
- Prefer `asyncio` over threads for I/O-bound concurrency

## Imports

- Stdlib first, third-party second, local third. Ruff enforces.
- Absolute imports within the project (`from orchestrator.agent import ...`), never relative

## Error handling

- Only catch exceptions you can meaningfully handle
- Re-raise with context, don't swallow
- Prefer specific exception types over bare `except`
- Let unexpected errors propagate to the orchestrator — it logs them to `events.jsonl`

## Experiment scripts

- Each `experiments/<id>/run.py` must be self-contained and idempotent
- Accept `--output-dir` as first arg, write all outputs there (logs, results JSON, plots)
- Exit code 0 on success, nonzero on failure — the skill parses this

## Reproducibility

- Seed all RNGs: `random.seed`, `numpy.random.seed`, `torch.manual_seed`
- Record the seed in the results JSON
- Pin dependency versions in `pyproject.toml`, not `requirements.txt`

## What NOT to do

- Don't `pip install` at runtime — add to `pyproject.toml` and ask the user to `uv sync`
- Don't write to `/tmp` — use `agent_results/<exp-id>/` so outputs are preserved
- Don't print fake progress (`[==> 50%]` hardcoded strings) — either measure real progress or say nothing
