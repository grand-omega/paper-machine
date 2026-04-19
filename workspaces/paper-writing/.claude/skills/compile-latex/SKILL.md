---
name: compile-latex
description: Compile the paper with pdflatex+bibtex, returning either success or the first real error. Use after any edit to paper/**.
---

# Skill: compile-latex

Standard LaTeX build protocol. Handles the pdflatex → bibtex → pdflatex → pdflatex dance and returns structured failure info when something breaks.

## Procedure

On macOS the TeX binaries live at `/Library/TeX/texbin/` but that path may not
be inherited into the subprocess environment. **Always prepend it.**

```bash
export PATH="/Library/TeX/texbin:$PATH"
cd paper
pdflatex -interaction=nonstopmode -halt-on-error main.tex > .build.log 2>&1
bibtex main >> .build.log 2>&1
pdflatex -interaction=nonstopmode -halt-on-error main.tex >> .build.log 2>&1
pdflatex -interaction=nonstopmode -halt-on-error main.tex >> .build.log 2>&1
```

Shortcut: run all four in one shell so the PATH export applies to all:

```bash
cd paper && export PATH="/Library/TeX/texbin:$PATH" && \
  pdflatex -interaction=nonstopmode -halt-on-error main.tex > .build.log 2>&1 && \
  bibtex main >> .build.log 2>&1 && \
  pdflatex -interaction=nonstopmode -halt-on-error main.tex >> .build.log 2>&1 && \
  pdflatex -interaction=nonstopmode -halt-on-error main.tex >> .build.log 2>&1
```

Check the last pdflatex exit code. If nonzero, extract the first error block:

```bash
grep -A 3 -E '^! ' .build.log | head -n 40
```

## Reporting success

On success, report:
- Output file: `paper/main.pdf` (size, page count from `pdfinfo main.pdf | grep Pages`)
- Any **warnings** (particularly: undefined references, missing citations, overfull hboxes > 20pt)

## Reporting failure

Return the **first** error, not all of them — LaTeX cascades and later errors are usually noise. Include:
- File and line
- Error message
- Three lines of context before the error

## Common fixes

| Error | Fix |
|---|---|
| `! Undefined control sequence \foo` | Missing package; add `\usepackage{...}` in `main.tex` |
| `! LaTeX Error: File 'foo.sty' not found` | Package not installed; surface to user rather than guessing |
| `! Package biblatex Error: File 'references.bib' not found` | Path / BibTeX isn't running — check working dir |
| `Citation 'key' undefined` | BibTeX entry missing; check `references.bib` |
| `Reference 'fig:name' undefined` | `\label{fig:name}` missing or misplaced (must be inside caption block) |
| `Overfull \hbox` | Rewrite the line; never ignore |

## Don't

- Don't run `pdflatex` without `-interaction=nonstopmode` — interactive mode hangs
- Don't suppress BibTeX errors — missing citations are bugs
- Don't commit `.aux`, `.log`, `.bbl`, `.pdf` files (already in `.gitignore`)
