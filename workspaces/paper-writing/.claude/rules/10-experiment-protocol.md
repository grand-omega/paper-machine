# Experiment protocol

## Experiment lifecycle

Every experiment transitions through these states in `experiments` table:

```
proposed → running → (completed | failed)
```

- **proposed**: row created by experimenter, no code run yet
- **running**: setup complete, execution in progress
- **completed**: finished with numerical results committed
- **failed**: finished with an error recorded

Use the `run-experiment` skill (via the `Skill` tool) to transition states — it handles the SQLite plumbing.

## Required fields for a completed experiment

| Field | Description |
|---|---|
| `id` | Auto-assigned UUID |
| `hypothesis` | One sentence: what we're testing |
| `method` | How we test it (script path + key parameters) |
| `metric` | What we're measuring (e.g. `runtime_ms`, `accuracy_top1`) |
| `baseline_value` | Value of the metric without the intervention |
| `treatment_value` | Value with the intervention |
| `effect_size` | `treatment - baseline` |
| `confidence` | Qualitative: `high` / `medium` / `low` with a one-line rationale |
| `raw_results_path` | Path to full output (log file, JSON, etc.) in `agent_results/` |

If any field is unknown, record `null` with a note in `lessons` rather than fabricating.

## Running code

- Experiments live in `experiments/<id>/` — one directory per experiment
- Scripts should be self-contained and runnable: `python experiments/<id>/run.py`
- Log stdout/stderr to `agent_results/<id>/run.log`
- Keep runtime bounded — if an experiment exceeds 10 minutes without progress, kill it and mark failed

## Failure recovery

- Up to **3 fix attempts** per experiment (dependency error, small bug, etc.)
- After 3 failures, mark `failed` with the accumulated error context in `lessons`
- Do NOT silently skip experiments — always record in SQLite

## What counts as a "good" experiment

- Addresses the foothold's research question
- Has a clear, measurable outcome
- Doesn't duplicate a prior completed experiment (check SQLite first)
- Runs in reasonable time (< 10 min default; note explicitly if longer)
