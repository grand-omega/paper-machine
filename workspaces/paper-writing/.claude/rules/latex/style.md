---
paths:
  - "**/*.tex"
  - "**/*.bib"
  - "paper/**"
---

# LaTeX style (loaded when working on paper files)

## Compilation

- Use `pdflatex -interaction=nonstopmode` via the `compile-latex` skill
- The skill captures the log and returns either success or the first real error
- Always bibtex between pdflatex runs: `pdflatex → bibtex → pdflatex → pdflatex`

## Structure

- One logical section per file under `paper/sections/`
- `main.tex` only does: documentclass, packages, `\input{sections/*}`
- No inline section content in `main.tex`

## Writing

- Present tense for current work (method, results). Past for background.
- First-person plural ("we show…") is fine
- Abstract: 150-250 words, no citations
- Introduction: one paragraph per: context, gap, contribution, results

## Math

- `\text{}` inside math mode for words
- Display equations: `\begin{equation} … \end{equation}` with a `\label{eq:name}`
- Reference as `\eqref{eq:name}`, not `Equation \ref{…}`

## Figures

- Drop in `paper/figures/` as PDF (never PNG except for screenshots)
- `\begin{figure}[tbp]` with `\centering`
- Caption at the bottom, `\label{fig:name}` after caption
- Generate from SQLite via scripts — never hand-copy data into TikZ

## Citations

- One `\cite{…}` per logical reference, not `\cite{a,b,c,d}` chains unless genuinely enumerating
- `\citep` for parenthetical, `\citet` for in-text, if using natbib

## Common mistakes to avoid

- `\ref{}` without a label defined — breaks the PDF silently
- BibTeX entry without `title` or `year` — logs a warning
- `$$…$$` display math (outdated) — use `\[…\]` or `equation` env
- `\label` before caption in figures — label refers to the section, not the figure
