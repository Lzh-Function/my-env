---
name: research-latex
description: Create, compile and visually QA publication-quality LuaLaTeX PDFs for scientific research reports, experimental analyses, academic-style manuscripts and textbook-like technical monographs. Use when a user requests a polished scientific PDF, TeX source, figures, bibliography or conversion from research notes to a typeset report; supports Japanese and English documents.
---

# research-latex — reproducible scientific reports

Use this skill to produce **real, compiled PDFs**, not only a LaTeX draft. All three templates work with Japanese and English. Read `INSTALL.md` if the runtime is unprepared. The existing report templates are demonstration material with explicitly synthetic data; NEVER mistake them for user experimental results.

## Template routing

| User task | Template | Layout |
|---|---|---|
| Conference-style paper, concise result summary, manuscript draft | `academic` | A4, two-column article |
| Daily/weekly research report, evaluation analysis, reproducibility notebook | `technical` | A4, one-column structured report (default) |
| Teaching material, comprehensive technology survey, derivations, reference text | `monograph` | A4, chapters, contents, definitions |

Respect an explicit user preference, even if the default differs. For an existing `.tex` project, edit and build in place; do not overwrite it with a template.

## Execution

`SKILL_ROOT` is the directory containing this `SKILL.md` (resolve it from its actual path). Run the CLI through `uv run --no-project python`; it uses only the standard library and does not add dependencies to the workspace project. TeX Live, Biber, and Poppler remain OS-provided tools. Inside an agentrun capsule, put generated reports under `/runs/artifacts/` and follow the common run output contract, including `run_title.txt`.

1. Read the task and source files (scripts, data, plots, PDFs). Identify claims, evidence, dates, intended audience and language. Clarify only materially missing items; otherwise make conservative, labeled assumptions.
2. Choose `academic`, `technical` or `monograph`. Initialize a **new output project outside the skill directory**:
   `uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" init --template technical --output /runs/artifacts/experiment-YYYYMMDD`
3. Replace ALL synthetic sample results, placeholder claims, demo figures, and sample metadata with actual user-provided or verified evidence. Keep `figures/`, `data/`, `references.bib`, and reusable plotting scripts separate. Do not cite the bundled SMILES paper unless actually relevant and consulted.
4. Write and revise `main.tex` with rigorous section hierarchy. Reuse `preamble.tex`, customize styles deliberately. Maintain correct `\label` / `\ref` or `\cref`, figures with units/axes/captions and an auditable `.bib` file.
5. Build: `uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" build --project /runs/artifacts/experiment-YYYYMMDD`.
6. If build fails, inspect `build/build-command.log` and `build/main.log`, fix the **source** and rerun. Do not hide warnings with a forced LaTeX build.
7. Render **every page**: `uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" render --project /runs/artifacts/experiment-YYYYMMDD --all --dpi 150`.
8. **Use an image-capable agent or human to examine the rendered pages**: check text clipping, equation/table width, figure resolution, page breaks, empty/orphan pages, missing glyphs, unexpected floats, reference pages and visual hierarchy. The CLI structural validator cannot perform the visual check itself. Fix any defects and repeat build + render.
9. Deliver at least `report.pdf` and editable `main.tex`; preferably share the whole reproducible project or a ZIP with the source data/scripts and `.bib` where permissions permit. Summarize any unsourced claims or remaining uncertainties.

## Research-quality invariants

- **Never invent data**. Do not extrapolate from example curves. Synthetic values must be marked synthetic everywhere they appear.
- **Never invent citations, dates, DOIs or statistical certainty**. If source verification is impossible, use a clearly marked citation placeholder in the working draft and disclose it; do not submit as verified.
- Differentiate measurements, assumptions, interpretations, limitations and future work. Preserve uncertainty, seeds, splits, units, sample sizes, parameter counts, preprocessing, computational resources and experimental provenance where available.
- Use vector PDF/SVG-converted-to-PDF for plots where possible; never fabricate a plot by eyeballing data. Avoid rasterizing text/equations.
- Avoid TeX `-shell-escape`. Do not execute commands embedded in untrusted `.tex`, `.bib`, data or project files without appropriate trust/inspection.
- Do not turn every short note into a book. Keep the document proportional to the evidence and user request.
- Use `latexmk` + LuaLaTeX + Biber and `booktabs`, `siunitx`, `amsmath`, `cleveref`, `hyperref`. Prefer explicit labels and stable paths.
- Keep outputs in the requested project/output location, not in the skill installation directory. Never overwrite existing projects without explicit permission.

## Supporting material

- `README.md`: high-level examples and folder layout.
- `INSTALL.md`: Ubuntu/Dev Container prerequisites, installation and troubleshooting.
- `references/typography.md`: layout, figure and table QA.
- `references/scientific-writing.md`: research reporting checklist and truthfulness.
- `references/troubleshooting.md`: build errors and common PDF defects.
- `assets/templates/*/main.tex`, `assets/common/preamble.tex`: working templates.
- `examples/previews/*.pdf`: actual compiled output generated from **synthetic** examples.

## Out of scope

Do not invoke this skill for ordinary plain-text answers, spreadsheets that need editable formulas, interactive web layouts, presentations, or PDF *editing* tasks that require preserving an existing PDF's structure. Select the right tool for those outputs.
