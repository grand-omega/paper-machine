---
paths:
  - "**/*.py"
  - "experiments/**"
  - "orchestrator/**"
---

# Python conventions (loaded when working on Python files)

## How to run Python (**mandatory**)

**Always invoke Python via `uv run python ...`**, never bare `python`.

- ✅ `uv run python experiments/X/run.py`
- ✅ `uv run python -m orchestrator.state --dump`
- ❌ `python experiments/X/run.py` — may hit system Python and miss project deps

`uv run` activates `.venv/` transparently. Bare `python` happens to resolve to the
venv when env is inherited cleanly, but don't rely on it — be explicit.

To add a dep, use `uv add <pkg>`. Never `pip install` anything.

**Default stance: permissive.** If you need a widely-used, well-maintained
scientific/visualization library to do the job well, add it. Don't hobble
the output for no reason.

**Good candidates to add without asking:**

- Visualization: `matplotlib`, `seaborn`, `plotly`
- Scientific: `scipy`, `statsmodels`, `scikit-learn`
- Utilities: `tqdm`, `joblib`, `pyarrow`
- Data: `yfinance`, `requests`, `beautifulsoup4` (if the foothold's domain needs)
- Plotting math: `sympy`

**Check the foothold before adding**:

- Domain-specific ML libraries (`torch`, `jax`, `transformers`) — usually fine
  but they're big; note in your response when pulling them in
- Anything the foothold's **"out of scope" section explicitly forbids** — if
  the foothold says "no deep learning," don't add torch. Surface to the
  orchestrator instead.

**Never add:**

- Anything that introduces a hard external dependency (paid API clients,
  proprietary binaries, platform-specific tooling) without flagging it
- Development-only tooling (`black`, `pytest`, `ipython`) unless explicitly
  needed for the work — keep runtime deps lean

**Already installed (as of current `pyproject.toml`):**

- `rich` — orchestrator's UI (don't import in experiment scripts)
- `yfinance`, `pandas`, `numpy`, `matplotlib` — project standard

Use `uv add <pkg>` freely within these rules. Always write imports explicitly
in scripts; don't rely on transitive imports.

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
