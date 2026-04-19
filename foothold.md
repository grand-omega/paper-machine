# Foothold — Smoke Test

> **This is a deliberate hello-world foothold to verify the pipeline works end-to-end.**
> Replace with your real research direction once the smoke test passes.

## Research question

Is Python's list comprehension syntax (`[f(x) for x in xs]`) measurably faster
than an equivalent `for`-loop with `list.append()`, for moderately-sized inputs
(N = 10_000 to 1_000_000 integer elements, single-pass squaring)?

## Hypothesis

List comprehensions are faster by a factor of roughly **1.3–2.0×** for these
sizes, due to the bytecode-level LIST_APPEND optimization in CPython that
avoids the method-lookup overhead of repeated `.append()` calls.

## Hardware / environment

- Hardware: whatever machine the pipeline is running on (agent: detect with
  `platform.uname()` and record it in the results)
- Python: 3.11+ (use `sys.version_info`)
- No external libraries required — **stdlib only** (`time.perf_counter`, `statistics`)

## Success criteria

The pipeline produces:

1. **At least one `completed` row** in `state/experiments.sqlite`
2. Each completed experiment has populated `baseline_value`, `treatment_value`,
   `effect_size`, and `confidence` fields
3. A LaTeX paper that compiles cleanly to `paper/main.pdf`
4. A `paper/review.md` with a verdict

The empirical answer is known (list-comp is faster); the smoke test is whether
the **framework machinery works**, not whether the agents discover something
novel.

## Scope constraints (to keep the run short)

- **Total budget: ~30 agent messages.** Don't propose more than 3 experiments.
- **Runtime cap per experiment: 30 seconds.** Measure with `timeit` or repeated
  `perf_counter` runs — 10 trials is plenty.
- **No external data**, no downloads, no network calls.
- **Paper target: 2 pages max.** A single results table, one figure optional.
- `related_works/` will be empty — the literature-reviewer should note this
  and proceed without failure.

## Out of scope

- Comparing across Python versions (just use whatever's installed)
- Comparing other languages
- Pypy / Cython / numba alternatives
- Memory profiling
- Anything requiring pip-installing something

## Related work

None provided for the smoke test — `related_works/` is intentionally empty.
The literature-reviewer should handle this gracefully: note the absence,
write a one-sentence `state/literature_review.md`, and produce an empty
`paper/references.bib`.

## Notes for the pipeline

This is a **smoke test**. The goal is to verify every phase runs without
crashing and produces the expected on-disk artifacts:

- `state/experiments.sqlite` with rows
- `state/literature_review.md`
- `paper/main.tex`, `paper/sections/*.tex`, `paper/main.pdf`
- `paper/review.md`
- `events.jsonl` with phase markers
- `.agent_state/*.session` UUIDs for each role

After a successful run, `just experiments` should print rows, and
`ls paper/` should show a `main.pdf`.
