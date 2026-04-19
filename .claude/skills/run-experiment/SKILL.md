---
name: run-experiment
description: Reproducible protocol for running a single experiment end-to-end — from setting up the directory, to execution, to parsing results back into SQLite. Use whenever an experiment needs to transition from `proposed` to `completed` or `failed`.
---

# Skill: run-experiment

The canonical procedure for running one experiment. Use this instead of ad-hoc bash.

## Inputs

- `experiment_id` — UUID from `experiments.id` in SQLite (must have status = `proposed`)

## Steps

### 1. Fetch the experiment spec

```bash
uv run python -m orchestrator.state --get {{experiment_id}}
```

This prints the row as JSON. Read: `hypothesis`, `method`, `metric`, expected baseline/treatment comparison.

### 2. Set up the experiment directory

```bash
mkdir -p experiments/{{experiment_id}}
mkdir -p agent_results/{{experiment_id}}
```

### 3. Write `experiments/{{experiment_id}}/run.py`

Your script must:
- Accept `--output-dir <path>` as first arg
- Write `results.json` to that dir on success (schema below)
- Exit 0 on success, nonzero on failure
- Log stdout/stderr — the orchestrator captures them

**`results.json` schema:**
```json
{
  "experiment_id": "<uuid>",
  "metric": "<name>",
  "baseline_value": <number>,
  "treatment_value": <number>,
  "effect_size": <number>,
  "confidence": "<high|medium|low>",
  "notes": "<one paragraph: what surprised you, what to trust>"
}
```

### 4. Mark running, execute, capture

```bash
uv run python -m orchestrator.state --set-status {{experiment_id}} running
uv run python experiments/{{experiment_id}}/run.py --output-dir agent_results/{{experiment_id}} \
    > agent_results/{{experiment_id}}/run.log 2>&1
EXIT=$?
```

### 5. Record outcome

On success:
```bash
uv run python -m orchestrator.state --complete {{experiment_id}} \
    --results agent_results/{{experiment_id}}/results.json \
    --raw-path agent_results/{{experiment_id}}/run.log
```

On failure:
```bash
uv run python -m orchestrator.state --fail {{experiment_id}} \
    --error-excerpt "$(tail -n 50 agent_results/{{experiment_id}}/run.log)" \
    --raw-path agent_results/{{experiment_id}}/run.log
```

### 6. Append a lesson if warranted

If you learned something worth remembering next round:

```bash
uv run python -m orchestrator.state --add-lesson \
    --experiment {{experiment_id}} \
    --text "..."
```

## Failure recovery

If the run script errored out due to a fixable issue (missing import, syntax error, wrong path), you may:
- Fix the script
- Re-execute step 4-5
- Up to 3 attempts total

After 3 attempts, mark failed with the error excerpt and move on. Don't loop forever.

## Don't

- Don't hand-write results into SQLite without a real run
- Don't call `sqlite3` directly — use `uv run python -m orchestrator.state` helpers so the schema is validated
- Don't delete `agent_results/<id>/` even on failure — the reviewer may want to see what happened
