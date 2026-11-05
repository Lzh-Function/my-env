# personal-slides

A personal PowerPoint skill: learn the user's practice from their template and past hand-made decks, then build new decks by cloning their own most similar slides and replacing the content.

All code and text here is original. It combines ideas from these projects (no code copied):

| Idea | From |
|---|---|
| Build new slides by editing the most similar reference slide; slide roles and content schemas | [PPTAgent](https://github.com/icip-cas/pptagent) |
| Index a slide library once (role, text slots), house-rule checker, keep a feedback log of user corrections | [pro-pptx-studio](https://github.com/Idriss-Mokdadi/pro-pptx-studio) |
| Separate profile → author → render stages; layout catalog of the template | [pptx-from-layouts-skill](https://github.com/tristan-mcinnis/pptx-from-layouts-skill) |
| Analyze a template once and keep the result as a written guideline | [Slide Agent](https://github.com/anyideaz/pptx-skills) |
| Render every slide and inspect the images; keep formatting when replacing text; never hand-edit packed output | [Anthropic pptx skill](https://github.com/anthropics/skills/tree/main/skills/pptx) |
| One message per slide, claim-stating titles, exhibit discipline for research talks | [academic-pptx-skill](https://github.com/gabberflast/academic-pptx-skill) |

## Layout

- `SKILL.md` — the workflow the agent follows.
- `references/` — how to write the style profile, the plan format, and general craft used only where the profile is silent.
- `scripts/slides` — wrapper running `scripts/slides.py` with python-pptx 1.0.2 and Pillow 11.3.0 through `uv`.
- `scripts/ooxml.py` — reads a .pptx completely from its XML (no python-pptx): effective formatting through the inheritance chain, equations, tables, charts, SmartArt, media, animations, notes, masters, layouts and theme; anything not interpreted is kept as XML. python-pptx is used only to build decks.

## Library

```
LIB/
  library.json      decks, hashes and original paths
  template.pptx     copy of the template
  decks/*.pptx      copies of the past decks (never modified)
  model/*.json      full XML model of each deck (re-read automatically when the reader improves)
  template-model.json  the template's masters, layouts and theme
  stats.md          measured statistics
  text/*.md         readable outlines with notes
  renders/*/        slide-N.png and grid.png (needs LibreOffice)
  style-profile.md  written by the agent from the evidence, confirmed by the user
  roles.json        role / exemplary / note per slide, written by the agent
  feedback.md       the user's corrections; highest priority
  fonts/            optional licensed fonts used for rendering
```

Tests: `python3 -m unittest tests.test_personal_slides` (requires `uv`; rendering is not covered without LibreOffice).
