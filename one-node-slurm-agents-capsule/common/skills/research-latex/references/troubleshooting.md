# Troubleshooting

## `fontspec Error: font ... cannot be found`

Run `doctor`. The provided preamble deliberately uses TeX Live's Latin Modern OTF fonts (`fonts-lmodern`) and HaranoAji Japanese fonts (`texlive-lang-japanese`) rather than requiring an arbitrary system font name. Do not swap to a font by intuition; check `kpsewhich FILE.otf` and actually compile.

## `Missing font identifier` or bold Japanese missing

With LuaTeX-ja/fontspec, specify bold Japanese fonts explicitly using the provided `\setmainjfont{HaranoAjiMincho-Regular.otf}[BoldFont=HaranoAjiMincho-Bold.otf]` pattern and equivalent sans face. Missing bold font mappings may cause failures in title/emphasis contexts.

## `Citation '...' undefined`

Check that the cite key exists in `references.bib`, `\addbibresource{references.bib}` is present, Biber is installed and latexmk can run it. Do not suppress errors; use `build` again and check `build/main.blg`.

## `! LaTeX Error: File '...sty' not found`

This is a missing TeX Live component. Run `doctor`, then install the matching OS TeX Live package (do not mix year-mismatched tlmgr and apt installations).

## `Overfull \hbox` or clipped plots

Reduce excess width rather than the document font globally. Use `tabularx`, shorter headings, `\includegraphics[width=\linewidth]{...}`, `\small` for table body, `\allowbreak` in long identifiers, `figure*` in two-column layouts, or split a large table. Re-render and visually inspect.

## Extremely slow first run

LuaLaTeX can populate font caches on initial execution, especially with large system CJK fonts. Using the bundled HaranoAji fonts minimizes variability. Repeated runs are typically much faster. Keep TeX intermediate output in `build/` and let latexmk handle multiple passes.

## Odd float order or huge blank space

Avoid indiscriminate `[H]` for scientific tables/figures. In monographs, chapter starts and frontmatter intentionally use additional pages; evaluate whether the document's *content* justifies its page count. A minimal demo monograph contains much more white space than a real technical book.

## Same Skill in WSL and Dev Container

Installation paths and binaries are environment-specific. A WSL-installed `lualatex` cannot automatically be called from an isolated Dev Container. Install TeX Live in the environment where the agent executes the build, or explicitly configure a trusted cross-environment build runner. The Skill's `SKILL.md` must also be visible to the agent process.

## Security

Never enable unrestricted shell escape simply to silence a compilation problem. LaTeX sources from unknown parties should be treated as potentially dangerous and built in a restricted container. The wrapper does not enable `-shell-escape`.
