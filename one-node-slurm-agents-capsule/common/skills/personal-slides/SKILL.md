---
name: personal-slides
description: Make PowerPoint (.pptx) decks the way this user makes them, by learning from their own template and past hand-made decks and reusing their slides. Use whenever the user asks for slides, a presentation, a talk deck, or to add their decks or template to the slide library; also use to learn or update their slide style profile.
---

# personal-slides — decks in the user's own style

This skill does not design slides from scratch. It learns how the user builds decks from their template and every past deck in a **slide library**, then builds each new slide by copying the user's most similar past slide (or a template layout) and replacing its content. Formatting, positions, colors and fonts come from the user's own slides; the agent decides structure and content following the learned **style profile**.

`SKILL_ROOT` is the directory containing this file. Run every command through the wrapper, which supplies python-pptx and Pillow without touching the project:

```bash
"$SKILL_ROOT/scripts/slides" <command> --library "$LIB" ...
```

## 0. Find the library

The library is a directory outside this read-only skill (template, copies of past decks, and what was learned). Use `$PERSONAL_SLIDES_LIBRARY` when it is set (then `--library` may be omitted); otherwise ask the user where it is or where to create it. Inside an agentrun capsule it must be on a bind mount the user keeps, never only in a run directory. Run `slides doctor --library "$LIB"` once per session: without LibreOffice nothing can be rendered, and fonts reported as `substituted` only change rendering, not the saved file (licensed font files may be put in `$LIB/fonts/`).

## 1. Learn (first use, and whenever decks are added)

1. `slides ingest --library "$LIB" --template TEMPLATE.pptx DECK_OR_FOLDER...` copies the decks (only new content hashes) and reads their complete XML into `model/<deck>.json`: every shape with absolute position, geometry, fill, line and effects; text with the formatting PowerPoint actually displays (inherited through layout, master, text styles and theme); equations (as LaTeX-like text), tables with merges and cell styling, chart types/data/axes, SmartArt trees, pictures with crop and alt text, connectors, backgrounds, transitions, animations, sections, comments and speaker notes; plus the masters, used layouts and theme. Elements the reader does not interpret are kept as XML excerpts in `uninterpreted`. It also writes `stats.md`, `text/<deck>.md` (readable outline with notes) and renders `renders/<deck>/slide-N.png` plus `grid.png`. `.ppt`/`.key` must be converted to `.pptx` first.
2. Study the evidence: read `stats.md`, every `text/*.md`, and look at every `renders/*/grid.png` (open individual slide images where the grid is too small). Image inspection is required; the numbers alone do not show visual habits. For exemplary or unusual slides read the full model with `slides show DECK:N`. When `uninterpreted` entries or the model leave something unclear, read the untouched XML with `slides raw DECK:N` (add `--part NAME` for any other part) instead of guessing.
   - Titles: many templates draw the title bar with a body placeholder or text box. `title.inferred: true` marks a title found by position and size; confirm it against the image.
3. Write or update `$LIB/style-profile.md` following [references/style-profile.md](references/style-profile.md). Every rule cites evidence (`deck:slide`, or a number from `stats.md`). Separate what the user always does from what they sometimes do.
4. Write `$LIB/roles.json`: for each slide `"deck:N": {"role": "...", "exemplary": true|false, "note": "..."}` using the role vocabulary in the profile. Mark as exemplary the slides that best show the user's practice; use `note` for when the slide is a good model and what it holds (e.g. "2 figures side by side with one-line takeaway").
5. Show the user the profile summary and ask for corrections. Their corrections override the evidence: record them verbatim with the date in `$LIB/feedback.md` and apply them to the profile.

When decks are added later, ingest only the new files, then update the profile and roles for the new slides; do not rewrite rules that the user has confirmed.

## 2. Plan

1. Read `style-profile.md` and `feedback.md` before anything else; feedback wins over the profile, and the profile wins over general advice in [references/craft.md](references/craft.md).
2. Read the source material (paper, results, notes). Never invent numbers, results or citations; mark anything missing as a question for the user instead of placeholder text.
3. Write the outline in the user's narrative pattern from the profile (opening, ordering, how results and conclusions are presented, slide count for the talk length). Write titles the way the profile says the user writes them.
4. For each slide choose a model: `slides find --library "$LIB" --role ROLE [--has picture|table|chart] [--text WORD] [--exemplary]`, look at the candidate images, then `slides show --library "$LIB" DECK:N` for its shapes. Prefer an exemplary slide with the same role and a similar amount of content. Use a template layout (`slides layouts`) only when no past slide fits.
5. Write `plan.json` next to the output (format in [references/plan.md](references/plan.md)). Keep each text within roughly the length of the text it replaces; split a slide rather than overfilling it. Delete model shapes that have no counterpart instead of leaving their old content.
6. Write speaker notes for every slide in the way the profile describes the user's notes (language, length, script or keywords). A cloned slide keeps its model's notes and their formatting until `notes` replaces them, so always set `notes` (or `""`) for cloned slides.

## 3. Build and inspect

1. `slides build --library "$LIB" --plan plan.json --out OUT.pptx` clones and fills the slides, runs `check`, renders `OUT-render/slide-N.png` and `grid.png`, and writes `OUT-report.md` (build notices such as layout fallbacks, fonts fixed against a different theme and embedded fonts, plus every check result).
2. Resolve every `[error]`. Treat each `[warn]` as a question to answer by looking at the image. The fit estimate is calibrated on the user's past slides: a warning means the text needs more room than any past slide used.
3. Look at **every** rendered slide image yourself: overflow, overlaps, leftover content from the model slide, broken figures, wrong emphasis, and departures from the profile. The checker estimates text fit; the image decides.
4. Fix the plan (shorter text, another model slide, split slides) and rebuild. Repeat until clean. Do not hand-edit the saved `.pptx`.

## 4. Deliver and learn

Deliver `OUT.pptx` with `plan.json`, `OUT-report.md` and the render grid; inside agentrun put them under `/runs/artifacts/`. In your reply to the user, state every build notice and remaining warning from `OUT-report.md` in plain words (which slide, what changed, why), together with unverified facts and slides whose model did not fit well; the report file keeps the same record for later. Ask for corrections; record them in `feedback.md`, and if they generalize, update `style-profile.md`.

## Rules

- Never fabricate data, figures, references or quotes. Reuse a past slide's figure only when it is the same figure; otherwise replace it or delete it.
- Old content must not leak: every text, picture, table and chart on a cloned slide is either replaced, deliberately kept (logos, footers) or deleted.
- Keep the library's copies unchanged; build into new files only.
- Japanese and English text follows the profile's wording rules. Use `yomiyasu` only when the user asks for it.
