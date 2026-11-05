# `plan.json`

```json
{
  "slides": [
    {"from": "talk-2025-ae3772:2",
     "fill": {"ph:0": "提案手法の要点",
              "ph:1": ["長い系列でも **精度を保つ**", {"text": "計算量は線形", "level": 1}]},
     "delete": [7],
     "notes": "ここで課題を強調する"},
    {"from": "talk-2025-ae3772:3",
     "fill": {"4": {"image": "figures/accuracy.png"},
              "5": {"table": [["手法", "精度"], ["提案", "0.95"]]},
              "6": {"chart": {"categories": ["A", "B"], "series": {"精度": [0.7, 0.95]}}}}},
    {"layout": "Title Only", "fill": {"ph:0": "まとめ"}}
  ]
}
```

Each slide has either:

- `from`: `DECK:NUMBER` of a past slide to clone (from `find`/`show`). Its layout is matched by name in the template; a warning is printed when it falls back to another layout.
- `layout`: a template layout name (from `layouts`), for slides with no suitable model.

Optional keys:

- `fill`: shape key → content. A key is a shape ID (`"4"`, from `show`), `ph:IDX` for a placeholder, or the exact shape name.
  - Text: a string (each line becomes a paragraph) or a list of strings / `{"text", "level"}`. Each level reuses the formatting of the model's paragraph at that level. `**bold**` marks emphasis inside a paragraph.
  - Mixed formatting inside a paragraph: `{"runs": [{"text": "計算量は "}, {"text": "O(n)", "style": 1}], "level": 0}`. `style: R` copies run R of the model paragraph used for that level; `style: [P, R]` copies run R of the model's paragraph P (indexes start at 0, as listed by `show`); optional `bold: true|false`. Use this to keep a font the user mixes in (code font, English font, colored keyword).
  - `{"image": PATH}` replaces a picture, cropped to fill the existing frame without stretching. Relative paths are resolved from the plan's directory.
  - `{"table": [[...], ...]}` fills a table row by row, keeping cell formatting; rows are added by copying the last row and removed from the end; columns cannot be added.
  - `{"chart": {"categories": [...], "series": {"name": [values]}}}` replaces the data of a category chart (bar, column, line, pie).
- `delete`: shape keys to remove (old content without a counterpart).
- `notes`: speaker notes, in the same forms as text (string, or list of strings / `{"text", "level"}`, with `**bold**`). The model slide's notes formatting is kept. Without `notes` a cloned slide keeps the model's notes, so replace or clear them (`""`).

Fonts: a cloned slide keeps its fonts. When its deck used a different theme or master than the template, the build writes the original displayed font and size onto each affected run and records it in the report; fonts embedded in the source decks are carried into the output.

Deleting or filling a group's member uses the member's own ID. Links from a cloned slide to other slides of its old deck are removed, since those slides are not copied.
