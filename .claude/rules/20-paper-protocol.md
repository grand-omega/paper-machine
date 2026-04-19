# Paper writing protocol

## File layout

```
paper/
├── main.tex                ← entry point
├── sections/
│   ├── abstract.tex
│   ├── introduction.tex
│   ├── related.tex
│   ├── method.tex
│   ├── results.tex
│   └── discussion.tex
├── figures/                ← auto-generated from experiments (run-experiment skill emits them)
├── tables/                 ← ditto
└── references.bib
```

## Section ownership

- `paper-writer` creates and revises everything under `paper/`
- `reviewer` reads only; it produces `paper/review.md` with comments

## Citation style

Use BibTeX `\cite{key}` with descriptive keys (`lastname_year_topic`, e.g. `karpathy_2024_scaling`). Drop BibTeX entries into `paper/references.bib` — don't cite papers that aren't in the bib file.

## Figures and tables

- Always generate from `state/experiments.sqlite` via a reproducible script in `paper/scripts/`
- Never hand-edit figure numbers in text — use `\ref{fig:name}` so adding a figure renumbers automatically
- Captions should tell the story of the figure in one sentence; details go in body text

## Prose constraints

- No em-dashes, no "delve", no "tapestry", no "realm". The user will notice.
- Use passive voice sparingly
- Every quantitative claim must reference a specific experiment id from SQLite
- Never invent numbers — if you need a value that's not in SQLite, say so and let the experimenter run it

## Revision workflow

1. `paper-writer` produces a full draft
2. `reviewer` (fresh eyes, no prior draft context) reads and writes `paper/review.md`
3. `paper-writer` addresses review comments, producing a new draft
4. Repeat until reviewer approves or `max_revisions` hit (configured in orchestrator)

The reviewer's approval criteria are in `.claude/agents/reviewer.md`.
