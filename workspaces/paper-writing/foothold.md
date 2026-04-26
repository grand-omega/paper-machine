# Foothold — GEMM optimization on CPU

## Research question

How close can a Python implementation of dense matrix multiplication (GEMM)
get to `numpy.matmul`'s BLAS-backed performance on square matrices in the
256–1024 range, on a single CPU core? Which classical HPC optimizations
(loop ordering, cache blocking, SIMD-friendly layout, parallelism) contribute
the most?

## Baseline

`numpy.matmul(A, B)` — calls the system BLAS (Accelerate on macOS,
OpenBLAS/MKL on Linux). This is the reference ceiling; candidates are
measured as a ratio of its GFLOPS.

## Primary metric

**GFLOPS** = `2·N³ / time_seconds / 1e9` for N×N matrices.

Report:
- Absolute GFLOPS of each candidate
- `GFLOPS_candidate / GFLOPS_numpy` (the gap to BLAS)
- Wall-clock time per run (for sanity)

## Hardware & run discipline

- Single CPU core for fair comparison: set `OMP_NUM_THREADS=1`,
  `MKL_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1` before imports
- Record `platform.uname()`, `os.cpu_count()`, CPU model in `results.json`
- Warm up (discard first run), then median of ≥ 5 trials for each size

## Deps

Pre-installed and allowed: `numpy`, `numba`, `matplotlib`, `pandas`,
stdlib. More via `uv add` if the planner/experimenter needs them
(see `.claude/rules/python/conventions.md` for the permissive policy).

## Expected outcomes (by theory — reality may differ)

- Pure Python triple loop: **1000× – 100,000× slower** than numpy
- Numba naive `@njit` triple loop: **10× – 100× slower**
- Numba + cache blocking / loop reordering: **2× – 10× slower**
- Numba + prange (multi-core): improves absolute speed but we compare
  single-threaded; report the scaling factor as a secondary result

Any claim that a hand-written implementation **matches or beats BLAS**
should trigger reviewer scrutiny. BLAS is the product of decades of
hand-tuned assembly; closing to within 2× is excellent, not beating it.

## Scope

- Square matrices: sizes `{256, 512, 1024}` (let the planner pick a subset)
- Single-precision `float32` (consistent with most ML workloads)
- Dense, contiguous, row-major
- Single-threaded baseline comparison

## Out of scope

- Sparse, banded, triangular multiplies
- Non-contiguous or strided arrays
- GPU, distributed, multi-node
- Mixed precision (fp16/bf16)
- Autograd / backprop
- Batched GEMM (`np.einsum`, etc.)

## Planning hints (for the planner)

Reasonable experiment candidates that isolate different optimization axes:

- Pure Python triple loop — "how bad is naive?"
- Numba `@njit` with default loop order — baseline-after-JIT
- Numba with `ikj` loop ordering (tighter inner-dim stride) vs `ijk`
- Numba with cache blocking (tile size as parameter)
- Numba with `parallel=True` + `prange` (parallel scaling, secondary result)

Pick **3** that together tell a coherent story. Don't sweep parameter grids
(p-hacking territory); pick fixed canonical values.

Each experiment should report:
- GFLOPS at each size tested
- Ratio to numpy baseline
- Enough context (loop order, tile size, thread count) to reproduce

## Literature hints (for literature-reviewer)

Web-search via WebFetch against scholar/arxiv:

- "Goto van de Geijn 2008 anatomy high-performance matrix multiplication"
- "BLIS framework linear algebra van Zee Smith"
- "Kazushige Goto GEMM cache blocking"
- "Numba performance GEMM benchmark"

Extract 4-6 key references. Cite the BLIS and Goto/van de Geijn papers
specifically if found — they're canonical.
