# Writing `style-profile.md`

The profile describes how this user makes decks, so that a new deck could pass as theirs. Write it in the user's working language. Each rule is short, concrete, and cites evidence: slide references such as `talk-2025-ae3772:7`, or numbers from `stats.md`. Mark each rule `always`, `usually` or `sometimes`. Do not copy generic presentation advice into it.

Use these sections.

## 1. Decks and narrative

- Kinds of decks in the library (lab meeting, conference talk, defense, lecture) and how each differs.
- Typical slide count per kind and per talk length.
- The opening sequence (title → outline? → background → problem …) and the closing sequence (summary, future work, acknowledgements, backup slides).
- How an argument is advanced: one claim per slide? question → answer? results before or after method details?
- Section dividers, outline slides, progress indicators: whether and how.

## 2. Slide roles

The vocabulary used in `roles.json`, derived from the user's decks (for example `title`, `outline`, `section`, `background`, `problem`, `method-overview`, `method-detail`, `setup`, `result-figure`, `result-table`, `comparison`, `discussion`, `summary`, `future`, `backup`, `acknowledgement`). For each role: what it contains, typical layout, and 1–3 exemplary slides.

## 3. Titles and text

- Title form: noun phrase, full-sentence takeaway, question; length (median/p90 from `stats.md`); punctuation.
- Body: bullets or prose, paragraph count and characters per slide (from `stats.md`), level-2 use, sentence endings (体言止め, である調, です・ます調), how numbers and units are written, Japanese/English mixing, abbreviations.
- Emphasis: bold, color, size, boxes — which, and how often.
- Speaker notes: used or not; language; full script or keywords; length (from `stats.md`); how they relate to the slide (narration, transitions, timing cues).
- Citations and sources: where and in what format.

## 4. Visual system

Read these from the models (`slides show`), not only from the images: effective sizes, fonts and colors are recorded per run, and shapes carry geometry, fill, line, effects and absolute boxes.

- Template layouts actually used, and for what.
- Fonts (Latin and East Asian), title/body sizes including inherited sizes seen in the renders.
- Colors: text, accent and fill colors with their meaning (e.g. red for the proposed method).
- Figures: size relative to the slide, one or several per slide, captions, axis labels, how a takeaway is attached to a figure.
- Tables: header style, highlighting the best value, number alignment.
- Recurring elements: logos, footers, page numbers, slide-corner labels.
- Spacing and density: margins, alignment habits, how full a slide is allowed to be.
- Diagrams: shape kinds (rounded boxes, arrows, connectors), outline and fill conventions, how flows are drawn.
- Equations: inline or display, size, whether explained in words.
- Motion: animations and transitions, if any, and what they are used for.

## 5. Do and don't

Concrete habits worth preserving and things the user never does, each with evidence. Corrections from `feedback.md` go here and take precedence.
