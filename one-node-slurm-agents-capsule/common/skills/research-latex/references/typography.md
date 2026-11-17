# Typesetting and figure/table standards

## Typography

- Use the provided LuaLaTeX preamble and Japanese `ltjsarticle` / `ltjsbook` document classes. Mixed scripts require coherent scale and line spacing.
- Prefer logical markup (`\section`, `\subsection`, `\emph`) over repeated manual font tweaking.
- Use `\label{sec:...}`, `\label{fig:...}`, `\label{tab:...}`, `\label{eq:...}` immediately after a caption or numbered heading; refer with `\cref`.
- Use `\eqref` or `\cref` for numbered equations, align multiline displays with `align`, and punctuate displayed equations as parts of sentences.
- Use `siunitx` (`\SI` in older configurations; `\qty` and `\unit` in current releases) if supported by your installed version; use `S` columns for numerical tables.
- Prefer `booktabs` (`\toprule`, `\midrule`, `\bottomrule`) instead of vertical gridlines; tables need a meaningful caption.
- Do not force `[H]` on every float. Inspect layout and choose controlled float placement when unavoidable.

## Vector figure hygiene

- Prefer PDF vectors (matplotlib `fig.savefig('figures/name.pdf')`), consistent readable text scale, labeled axes, units and legible legends.
- For 2-column article, use `\columnwidth` for ordinary figures, and `figure*` + `\textwidth` for genuine two-column spans.
- Raster images are acceptable for photographs or microscopy; avoid converting plots with thin lines into low-resolution PNG.
- Preserve figure generation scripts and raw data. Don't tweak chart geometry to imply unsupported effects.
- In `academic`, check that single-column floats do not drift into the wrong section; two-column wide floats often have restricted placement.

## Page QA procedure

1. Build without errors and check the bibliography actually appears.
2. Render in two stages so the procedure stays feasible for long documents:
   - **After each fix**: run `render --changed --dpi 150`. It rasterizes the PDF, compares each page with the last render, and writes only the changed pages plus one page on each side. Review those.
   - **First render and before delivery**: run `render --all --dpi 150` once and review every page.
3. Review **each PNG produced** for text clipping/overlap, footer and page numbers, float placement, oversized white gaps, orphan headings, blank pages and broken glyphs.
4. Especially check: first page title+abstract, dense result pages, appendices, bibliography, very wide equations and full-page tables.
5. Check hyperlinked citations, figure/table cross-references and text extraction. Verify English symbols and Japanese glyphs.
6. If any defect exists, edit TeX, rebuild, run `render --changed` and recheck the pages it writes.

A programmatic `validate` success is **not** a visual pass. The Skill cannot claim visual verification unless an actual image-capable agent or human inspected all relevant rendered pages, and all pages at least once before delivery.
