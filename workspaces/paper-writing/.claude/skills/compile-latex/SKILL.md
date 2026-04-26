---
name: compile-latex
description: Compile the paper with pdflatex+bibtex inside the LaTeX container. Returns either success or the first real error. Use after any edit to paper/**.
---

# Skill: compile-latex

All LaTeX tooling runs inside a Podman/Docker container (image:
`paper-machine-latex:latest`, built by `just build-image`). Invoke commands
through `scripts/run-latex` — it handles mounting `paper/` into the
container and picks podman or docker automatically.

## Procedure

Run each pass from the workspace root (not from inside `paper/`). The
wrapper mounts `paper/` as `/paper` and `cd`s into it.

```bash
scripts/run-latex pdflatex -interaction=nonstopmode -halt-on-error main.tex > paper/.build.log 2>&1
scripts/run-latex bibtex main >> paper/.build.log 2>&1
scripts/run-latex pdflatex -interaction=nonstopmode -halt-on-error main.tex >> paper/.build.log 2>&1
scripts/run-latex pdflatex -interaction=nonstopmode -halt-on-error main.tex >> paper/.build.log 2>&1
```

For biblatex/biber workflows, swap `bibtex main` for `biber main`.

Chained invocation (single shell inside the container):

```bash
scripts/run-latex bash -c "pdflatex -interaction=nonstopmode -halt-on-error main.tex \
  && bibtex main \
  && pdflatex -interaction=nonstopmode -halt-on-error main.tex \
  && pdflatex -interaction=nonstopmode -halt-on-error main.tex" > paper/.build.log 2>&1
```

## Other useful commands in the container

```bash
scripts/run-latex kpsewhich <pkg>.sty         # check if a package is present
scripts/run-latex pdfinfo main.pdf            # verify page count / size
scripts/run-latex pdftotext -layout main.pdf - | head   # inspect rendered text
```

## Reporting success

On success:
- Output file: `paper/main.pdf`
- Size + pages: `scripts/run-latex pdfinfo main.pdf | grep -E 'Pages|File size'`
- Any **warnings** (particularly: undefined references, missing citations, overfull hboxes > 20pt)

## Reporting failure

Return the **first** error — LaTeX cascades and later errors are usually
noise. Extract:
```bash
grep -A 3 -E '^! ' paper/.build.log | head -n 40
```

## Common fixes

| Error | Fix |
|---|---|
| `! Undefined control sequence \foo` | Missing package; add `\usepackage{...}` in `main.tex` |
| `! LaTeX Error: File 'foo.sty' not found` | Package not in container — add to `Containerfile`'s `tlmgr install` list and rebuild with `just build-image` |
| `Citation 'key' undefined` | BibTeX entry missing; check `paper/references.bib` |
| `Reference 'fig:name' undefined` | `\label{fig:name}` missing or misplaced (must be inside caption block) |
| `Overfull \hbox` | Rewrite the line; never ignore |

## Don't

- Don't run `pdflatex` directly on the host — it may not be installed
  there. Always go through `scripts/run-latex`.
- Don't run `pdflatex` without `-interaction=nonstopmode` — interactive
  mode hangs in a container.
- Don't suppress BibTeX/biber errors — missing citations are bugs.
- Don't commit `.aux`, `.log`, `.bbl`, `.pdf` files (already in `.gitignore`).
- Don't `tlmgr install` ad-hoc at runtime — installed packages don't
  persist across `scripts/run-latex` invocations (each is a fresh
  container). Add to `Containerfile` and `just build-image` instead.
