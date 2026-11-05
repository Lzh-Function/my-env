#!/usr/bin/env python3
"""Learn the user's slide practice from their template and past decks, and build new decks
by reusing their own slides.

Run through the `slides` wrapper next to this file, which supplies python-pptx and Pillow.
Subcommands: doctor, ingest, find, show, layouts, build, check, render.
"""

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata

from lxml import etree
import ooxml
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import Part, _Relationship
from pptx.opc.packuri import PackURI
from pptx.oxml.ns import qn

R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EMU_PER_PT = 12700
# Text that means a slide was left unfinished.
LEFTOVER = re.compile(r"lorem|ipsum|\bx{3,}\b|\bTODO\b|\bTBD\b|＿{2,}|_{4,}|\[(?:insert|ここに)[^\]]*\]|"
                      r"click to (?:add|edit)|クリックして|テキストを入力", re.IGNORECASE)
LIBRARY = {"required": True}
SKIP_RELS = {RT.SLIDE_LAYOUT, RT.NOTES_SLIDE, RT.COMMENTS}


def fail(message):
    print("error: " + message, file=sys.stderr)
    sys.exit(2)


def pt(emu):
    return round((emu or 0) / EMU_PER_PT, 1)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n")
    os.replace(temporary, path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


# ---------------------------------------------------------------- library


class Library:
    """A directory holding the template, copies of past decks and what was learned from them."""

    def __init__(self, root, create=False):
        self.root = Path(root).expanduser().resolve()
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        elif not (self.root / "library.json").is_file():
            fail(f"{self.root} is not a slide library; run `ingest` first")
        self.meta = read_json(self.root / "library.json", {"template": None, "decks": {}})

    def save(self):
        write_json(self.root / "library.json", self.meta)

    @property
    def template(self):
        if not self.meta.get("template"):
            fail("the library has no template; run `ingest --template FILE`")
        return self.root / self.meta["template"]

    def deck_path(self, deck):
        if deck not in self.meta["decks"]:
            fail(f"unknown deck id: {deck} (see library.json or `find`)")
        return self.root / self.meta["decks"][deck]["file"]

    def deck_path_unchecked(self, deck):
        return self.root / "decks" / f"{deck}.pptx"

    def model_path(self, deck):
        return self.root / "model" / f"{deck}.json"

    def models(self):
        """Full XML models of every deck, keyed by deck ID."""
        if not hasattr(self, "_models"):
            self._models = {deck: read_json(self.model_path(deck)) for deck in self.meta["decks"]}
            missing = [deck for deck, model in self._models.items() if model is None]
            if missing:
                fail(f"models are missing for {', '.join(missing)}; run `ingest --reextract`")
        return self._models

    def slide(self, key):
        deck, _, number = str(key).rpartition(":")
        model = self.models().get(deck)
        if model is None or not number.isdigit() or not 1 <= int(number) <= len(model["slides"]):
            fail(f"unknown slide {key}; give DECK:NUMBER from `find`")
        return model["slides"][int(number) - 1]

    def roles(self):
        return read_json(self.root / "roles.json", {})


def deck_id(path, digest):
    stem = re.sub(r"[^0-9A-Za-z぀-ヿ一-鿿]+", "-", Path(path).stem).strip("-")[:40] or "deck"
    return f"{stem}-{digest[:6]}"


# ---------------------------------------------------------------- reading the model

TITLE_KINDS = {"title", "ctrTitle"}
META_KINDS = {"dt", "ftr", "sldNum"}


def flatten(shapes):
    for shape in shapes:
        yield shape
        yield from flatten(shape.get("children", []))


def placeholder_kind(shape):
    return (shape.get("placeholder") or {}).get("type")


def is_title(shape, slide):
    title = slide.get("title")
    return bool(title) and shape.get("id") == title["shape_id"] or placeholder_kind(shape) in TITLE_KINDS


def slide_title(slide):
    return (slide.get("title") or {}).get("text")


def body_shapes(slide):
    return [s for s in flatten(slide["shapes"]) if s.get("text") and not is_title(s, slide)
            and placeholder_kind(s) not in META_KINDS]


def visible_runs(shape):
    for paragraph in (shape.get("text") or {}).get("paragraphs", []):
        for run in paragraph["runs"]:
            if run["text"].strip():
                yield paragraph, run


def slide_text(slide):
    parts = [slide_title(slide) or ""]
    for shape in flatten(slide["shapes"]):
        parts += [p["text"] for p in (shape.get("text") or {}).get("paragraphs", [])]
        parts += [cell.get("text", "") for row in (shape.get("table") or {}).get("rows", []) for cell in row["cells"]]
        parts += texts_of_tree((shape.get("smartart") or {}).get("nodes", []))
        chart = shape.get("chart") or {}
        parts += [chart.get("title") or ""] + [s.get("name") or "" for p in chart.get("plots", []) for s in p["series"]]
    parts.append((slide.get("notes") or {}).get("text", ""))
    return " ".join(p for p in parts if p)


def texts_of_tree(nodes):
    result = []
    for node in nodes:
        result.append(node["text"])
        result += texts_of_tree(node["children"])
    return result


# ---------------------------------------------------------------- statistics


def percentiles(values):
    if not values:
        return "-"
    values = sorted(values)
    pick = lambda q: values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))]  # noqa: E731
    return f"median {pick(0.5):g} / p10 {pick(0.1):g} / p90 {pick(0.9):g} (n={len(values)})"


def tally(counter, key, weight=1):
    if key not in (None, "", [], {}):
        key = json.dumps(key, ensure_ascii=False, sort_keys=True) if isinstance(key, (dict, list)) else key
        counter[key] = counter.get(key, 0) + weight


def table(title, counter, limit=20, header=("value", "count")):
    rows = sorted(counter.items(), key=lambda item: -item[1])[:limit]
    body = "\n".join(f"| {key} | {value:g} |" for key, value in rows) or "| - | - |"
    more = f"\n\n({len(counter) - limit} more)" if len(counter) > limit else ""
    return f"\n## {title}\n\n| {header[0]} | {header[1]} |\n|---|---|\n{body}{more}\n"


def color_name(color):
    if not isinstance(color, dict) or not color.get("rgb"):
        return None
    return color["rgb"] + (f" ({color['scheme']})" if color.get("scheme") else "")


def statistics_markdown(models):
    counters = {name: {} for name in (
        "layouts", "title_size", "title_font", "title_color", "title_align", "body_size", "body_font",
        "text_color", "body_align", "line_spacing", "space_before", "space_after", "bullets", "levels", "emphasis",
        "geometry", "shape_fill", "line", "effects", "picture", "table", "chart", "smartart", "animation",
        "transition", "background", "uninterpreted", "anchor", "autofit")}
    title_lengths, body_chars, paragraphs, shape_counts, notes_lengths, lengths = [], [], [], [], [], []
    presence = {k: 0 for k in ("picture", "table", "chart", "smartart", "equation", "animation", "notes",
                               "connector", "group", "alt_text")}
    slides = [s for m in models.values() for s in m["slides"] if not s["hidden"]]
    for model in models.values():
        lengths.append(len([s for s in model["slides"] if not s["hidden"]]))
    for slide in slides:
        tally(counters["layouts"], slide["layout"])
        tally(counters["transition"], (slide.get("transition") or {}).get("effect"))
        tally(counters["background"], json.dumps(slide.get("background"), ensure_ascii=False)
              if slide.get("background") else "(layout/master)")
        title = slide_title(slide)
        if title:
            title_lengths.append(len(title))
        if (slide.get("notes") or {}).get("text"):
            presence["notes"] += 1
            notes_lengths.append(len(slide["notes"]["text"]))
        effects = [a for a in slide.get("animations", []) if "class" in a]
        if effects:
            presence["animation"] += 1
        for effect in effects:
            tally(counters["animation"], f"{effect['class']}:{effect.get('name') or effect['preset']} "
                                         f"({effect['trigger']})")
        for item in slide.get("uninterpreted", []):
            tally(counters["uninterpreted"], (item["path"] or "").rsplit("/", 1)[-1] or "(more)")
        shapes = list(flatten(slide["shapes"]))
        shape_counts.append(len(shapes))
        kinds = {s["kind"] for s in shapes}
        for kind in ("picture", "table", "chart", "smartart", "connector", "group"):
            presence[kind] += kind in kinds
        presence["alt_text"] += any(s.get("alt_text") for s in shapes if s["kind"] == "picture")
        presence["equation"] += any(r.get("math") for s in shapes for _, r in visible_runs(s))
        chars = count = 0
        for shape in shapes:
            tally(counters["geometry"], shape.get("geometry") if shape["kind"] == "shape" else None)
            if shape["kind"] in ("shape", "connector"):
                fill = shape.get("fill") or {}
                tally(counters["shape_fill"], color_name(fill.get("color")) if fill.get("type") == "solid"
                      else fill.get("type"))
                line = shape.get("line") or {}
                if line and not line.get("none"):
                    tally(counters["line"], f"{color_name(line.get('color')) or '-'} {line.get('width_pt', '-')}pt "
                                            f"{line.get('dash', 'solid')}"
                                            + (" arrow" if line.get("tailEnd") or line.get("headEnd") else ""))
                for effect in shape.get("effects", []):
                    tally(counters["effects"], effect["type"])
            if shape["kind"] == "picture":
                image = shape.get("image") or {}
                tally(counters["picture"], f"{image.get('ext')}{' svg' if image.get('svg') else ''}"
                                           f"{' cropped' if shape.get('crop') else ''}")
            if shape.get("table"):
                header = shape["table"]["rows"][0]["cells"][0] if shape["table"]["rows"] else {}
                tally(counters["table"], f"style {shape['table']['style_id']} header "
                                         f"{color_name((header.get('fill') or {}).get('color')) or '-'}")
            if shape.get("chart"):
                chart = shape["chart"]
                tally(counters["chart"], ", ".join(p["type"] for p in chart.get("plots", []))
                      + f" legend={chart.get('legend')}")
            if shape.get("smartart"):
                tally(counters["smartart"], shape["smartart"].get("layout_title") or shape["smartart"].get("layout"))
            text = shape.get("text")
            if not text:
                continue
            tally(counters["anchor"], text["body"].get("anchor"))
            tally(counters["autofit"], text["body"].get("autofit", "none"))
            title_shape = is_title(shape, slide)
            body = not title_shape and placeholder_kind(shape) not in META_KINDS
            for paragraph in text["paragraphs"]:
                if not paragraph["text"].strip():
                    continue
                fmt = paragraph["format"]
                tally(counters["title_align" if title_shape else "body_align"], fmt.get("align"))
                if body:
                    count += 1
                    chars += len(paragraph["text"])
                    tally(counters["levels"], paragraph["level"])
                    tally(counters["line_spacing"], fmt.get("lnSpc", "100%"))
                    tally(counters["space_before"], fmt.get("spcBef", "0"))
                    tally(counters["space_after"], fmt.get("spcAft", "0"))
                    tally(counters["bullets"], f"level {paragraph['level']}: "
                                               + json.dumps(fmt.get("bullet", {"type": "inherited-none"}),
                                                            ensure_ascii=False))
                for run in paragraph["runs"]:
                    weight = len(run["text"].strip())
                    if not weight:
                        continue
                    prefix = "title" if title_shape else "body"
                    tally(counters[prefix + "_size"], run.get("size"), weight)
                    tally(counters[prefix + "_font"], f"{run.get('latin')} / {run.get('ea')}", weight)
                    tally(counters["title_color" if title_shape else "text_color"],
                          color_name(run.get("color")), weight)
                    marks = [k for k in ("bold", "italic", "underline") if run.get(k)]
                    if run.get("color") and body:
                        marks.append("color " + (color_name(run["color"]) or ""))
                    if run.get("highlight"):
                        marks.append("highlight")
                    tally(counters["emphasis"], " + ".join(marks) if marks else "plain", weight)
        body_chars.append(chars)
        paragraphs.append(count)
    total = max(1, len(slides))
    lines = [
        "# Corpus statistics (generated)", "",
        "Measured from the full XML of the past decks with inheritance resolved (sizes, fonts and colors are the",
        "values PowerPoint displays). Regenerate with `ingest`. Use these numbers as evidence in style-profile.md.", "",
        f"- Decks: {len(models)}; visible slides: {len(slides)}; slides per deck: {percentiles(lengths)}",
        f"- Slide sizes (pt): {sorted({tuple(m['size']) for m in models.values() if m.get('size')})}",
        f"- Title length (chars): {percentiles(title_lengths)}; titles inferred from position (no title "
        f"placeholder): {sum(1 for s in slides if (s.get('title') or {}).get('inferred'))} of {len(slides)} slides",
        f"- Body paragraphs per slide: {percentiles(paragraphs)}",
        f"- Body characters per slide: {percentiles(body_chars)}",
        f"- Shapes per slide: {percentiles(shape_counts)}",
        f"- Notes length (chars, slides with notes): {percentiles(notes_lengths)}",
        "- Slides containing: " + ", ".join(f"{k} {v / total:.0%}" for k, v in presence.items()),
    ]
    titles = {"layouts": "Layout use (slides)", "title_size": "Title font size (pt, by characters)",
              "title_font": "Title fonts latin / east-asian (by characters)", "title_color": "Title colors",
              "title_align": "Title alignment (paragraphs)", "body_size": "Body font size (pt, by characters)",
              "body_font": "Body fonts latin / east-asian (by characters)", "text_color": "Body text colors",
              "body_align": "Body alignment", "levels": "Body paragraph levels", "line_spacing": "Line spacing",
              "space_before": "Space before paragraphs", "space_after": "Space after paragraphs",
              "bullets": "Bullets by level", "emphasis": "Emphasis in body text (by characters)",
              "anchor": "Text anchoring", "autofit": "Autofit", "geometry": "Shape geometry",
              "shape_fill": "Shape fills", "line": "Lines and outlines (color width dash)", "effects": "Shape effects",
              "picture": "Pictures", "table": "Tables (style, header fill)", "chart": "Charts",
              "smartart": "SmartArt layouts", "animation": "Animations (class:effect, trigger)",
              "transition": "Transitions", "background": "Slide backgrounds",
              "uninterpreted": "Uninterpreted XML elements (inspect with `raw`)"}
    for key, title in titles.items():
        lines.append(table(title, counters[key]))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- readable outline


def run_text(paragraph):
    return "".join(f"${r['text']}$" if r.get("math") else r["text"] for r in paragraph["runs"])


def describe(shape, slide, indent=""):
    lines = []
    label = placeholder_kind(shape) or shape.get("geometry") or shape["kind"]
    if is_title(shape, slide):
        label = "TITLE " + label
    if shape.get("text"):
        for paragraph in shape["text"]["paragraphs"]:
            text = run_text(paragraph)
            if text.strip():
                lines.append(f"{indent}{'  ' * paragraph['level']}- ({label}) {text}")
    if shape["kind"] == "group":
        lines.append(f"{indent}- [group {shape['id']}]")
        for item in shape["children"]:
            lines += describe(item, slide, indent + "  ")
    elif shape.get("table"):
        rows = shape["table"]["rows"]
        lines.append(f"{indent}- [table {len(rows)}x{len(rows[0]['cells']) if rows else 0}]")
        for row in rows[:12]:
            cells = ["<merged>" if c.get("hMerge") or c.get("vMerge") else c.get("text", "").replace("\n", " ")
                     for c in row["cells"]]
            lines.append(f"{indent}  | " + " | ".join(cells) + " |")
    elif shape.get("chart"):
        chart = shape["chart"]
        lines.append(f"{indent}- [chart {', '.join(p['type'] for p in chart.get('plots', []))}] "
                     f"title={chart.get('title')!r} axes={[a.get('title') for a in chart.get('axes', [])]}")
        for plot in chart.get("plots", []):
            for series in plot["series"]:
                values = (series.get("val") or series.get("yVal") or {}).get("values")
                categories = (series.get("cat") or series.get("xVal") or {}).get("values")
                lines.append(f"{indent}  - {series.get('name')}: {values} over {categories}")
    elif shape.get("smartart"):
        lines.append(f"{indent}- [SmartArt {shape['smartart'].get('layout_title')}]")

        def nodes(items, depth):
            for node in items:
                lines.append(f"{indent}  {'  ' * depth}- {node['text']}")
                nodes(node["children"], depth + 1)

        nodes(shape["smartart"]["nodes"], 0)
    elif shape["kind"] == "picture":
        image = shape.get("image") or {}
        lines.append(f"{indent}- [picture {image.get('ext')} {image.get('pixels') or ''}"
                     f"{' alt=' + repr(shape['alt_text']) if shape.get('alt_text') else ''}]")
    elif shape["kind"] == "connector" and (shape.get("stCxn") or shape.get("endCxn")):
        lines.append(f"{indent}- [connector {shape.get('stCxn', {}).get('shape_id')} -> "
                     f"{shape.get('endCxn', {}).get('shape_id')}]")
    return lines


def text_markdown(deck, model):
    lines = [f"# {deck}", ""]
    for slide in model["slides"]:
        extra = [x for x in ("hidden" if slide["hidden"] else None,
                             f"section {slide['section']}" if slide.get("section") else None) if x]
        lines.append(f"## {deck}:{slide['number']} [{slide['layout']}]" + (f" ({', '.join(extra)})" if extra else ""))
        ordered = sorted(slide["shapes"], key=lambda s: ((s.get("box") or {}).get("y", 0), (s.get("box") or {}).get("x", 0)))
        for shape in ordered:
            lines += describe(shape, slide)
        effects = [a for a in slide.get("animations", []) if "class" in a]
        if effects:
            lines.append("- animations: " + "; ".join(
                f"click {a['click']} {a['class']}:{a.get('name') or a['preset']} shape {a['shape_id']}" for a in effects))
        if slide.get("transition"):
            lines.append(f"- transition: {slide['transition'].get('effect')}")
        notes = (slide.get("notes") or {}).get("text", "")
        if notes:
            lines.extend("> " + line for line in notes.splitlines())
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- rendering


def slide_number(path):
    return int(re.findall(r"\d+", Path(path).stem)[-1])


def font_config(font_dirs, scratch):
    dirs = [Path(d) for d in font_dirs if d and Path(d).is_dir()]
    if not dirs:
        return {}
    config = Path(scratch) / "fonts.conf"
    config.write_text(
        '<?xml version="1.0"?><fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include>'
        + "".join(f"<dir>{d.resolve()}</dir>" for d in dirs)
        + f"<cachedir>{Path(scratch).resolve() / 'fontcache'}</cachedir></fontconfig>")
    return {"FONTCONFIG_FILE": str(config)}


def office():
    return shutil.which("soffice") or shutil.which("libreoffice")


def render(pptx, out_dir, dpi=80, font_dirs=(), grid=True, label=None):
    """Render every slide to PNG through LibreOffice and Poppler; return the image paths."""
    binary = office()
    if binary is None or shutil.which("pdftoppm") is None:
        raise RuntimeError("rendering needs LibreOffice (soffice) and Poppler (pdftoppm); see `doctor`")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("slide-*.png"):
        old.unlink()
    with tempfile.TemporaryDirectory(prefix="slides-render-") as scratch:
        env = dict(os.environ, **font_config(font_dirs, scratch))
        # A private profile lets several renders run at once without LibreOffice's lock.
        subprocess.run([binary, f"-env:UserInstallation=file://{scratch}/profile", "--headless",
                        "--convert-to", "pdf", "--outdir", scratch, str(pptx)],
                       check=True, capture_output=True, timeout=600, env=env)
        pdf = Path(scratch) / (Path(pptx).stem + ".pdf")
        if not pdf.is_file():
            raise RuntimeError("LibreOffice produced no PDF for " + str(pptx))
        shutil.copyfile(pdf, out_dir / "deck.pdf")
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(out_dir / "slide")],
                       check=True, capture_output=True, timeout=600)
    images = sorted(out_dir.glob("slide-*.png"), key=slide_number)
    # Name images slide-N.png regardless of pdftoppm's zero padding.
    named = []
    for path in images:
        target = out_dir / f"slide-{slide_number(path)}.png"
        if path != target:
            path.rename(target)
        named.append(target)
    if grid and named:
        contact_sheet(named, out_dir / "grid.png", label or Path(pptx).stem)
    return named


def contact_sheet(images, target, label, columns=4, width=360):
    from PIL import Image, ImageDraw
    thumbs = []
    for path in images:
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((width, width))
            thumbs.append((path, image.copy()))
    cell_h = max(t.height for _, t in thumbs) + 22
    rows = math.ceil(len(thumbs) / columns)
    sheet = Image.new("RGB", (columns * (width + 10) + 10, rows * (cell_h + 10) + 10), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (path, thumb) in enumerate(thumbs):
        x, y = 10 + (index % columns) * (width + 10), 10 + (index // columns) * (cell_h + 10)
        sheet.paste(thumb, (x, y + 20))
        draw.rectangle([x, y + 20, x + thumb.width - 1, y + 19 + thumb.height], outline="#999999")
        draw.text((x, y + 4), f"{label}:{slide_number(path)}", fill="black")
    sheet.save(target)


# ---------------------------------------------------------------- building


def walk_shapes(shapes, parent=None):
    for shape in shapes:
        yield shape, parent
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from walk_shapes(shape.shapes, shape.shape_id)


class Builder:
    """Clone slides from past decks into a copy of the template, then fill them."""

    def __init__(self, library):
        self.library = library
        self.prs = Presentation(library.template)
        self.sources = {}
        self.copied = {}
        self.reserved = set()
        self.warnings = []
        # Start from the template's masters and layouts only.
        slide_ids = self.prs.slides._sldIdLst
        for slide_id in list(slide_ids):
            self.prs.part.drop_rel(slide_id.rId)
            slide_ids.remove(slide_id)

    def layouts(self):
        return [layout for master in self.prs.slide_masters for layout in master.slide_layouts]

    def layout(self, name, source=None):
        layouts = self.layouts()
        for layout in layouts:
            if layout.name == name:
                return layout
        for layout in layouts:
            if layout.name.casefold() == str(name).casefold():
                return layout
        if source is not None:
            # Fall back to the template layout with the same placeholder kinds.
            wanted = sorted(str(p.placeholder_format.type) for p in source.placeholders)
            for layout in layouts:
                if sorted(str(p.placeholder_format.type) for p in layout.placeholders) == wanted:
                    self.warnings.append(f"layout '{name}' is not in the template; used '{layout.name}'")
                    return layout
        if source is None:
            fail(f"the template has no layout named '{name}'; see `layouts`")
        self.warnings.append(f"layout '{name}' is not in the template; used '{layouts[0].name}'")
        return layouts[0]

    def source(self, deck):
        if deck not in self.sources:
            self.sources[deck] = Presentation(self.library.deck_path(deck))
        return self.sources[deck]

    def partname(self, original):
        template = re.sub(r"\d*(\.\w+)$", r"%d\1", str(original))
        if "%d" not in template:
            template = str(original) + "%d"
        existing = {str(p.partname) for p in self.prs.part.package.iter_parts()} | self.reserved
        number = 1
        while template % number in existing:
            number += 1
        self.reserved.add(template % number)
        return PackURI(template % number)

    def copy_part(self, part, deck):
        key = (deck, str(part.partname))
        if key in self.copied:
            return self.copied[key]
        clone = Part(self.partname(part.partname), part.content_type, self.prs.part.package, part.blob)
        self.copied[key] = clone
        # Keep relationship IDs so references inside the copied XML stay valid.
        for rId, rel in part.rels.items():
            if rel.is_external:
                target, mode = rel.target_ref, "External"
            elif rel.reltype in (RT.SLIDE, RT.NOTES_SLIDE, RT.SLIDE_LAYOUT):
                continue
            else:
                target, mode = self.copy_part(rel.target_part, deck), "Internal"
            clone.rels._rels[rId] = _Relationship(clone.rels._base_uri, rId, rel.reltype, mode, target)
        return clone

    def clone(self, deck, number):
        source_prs = self.source(deck)
        if not 1 <= number <= len(source_prs.slides):
            fail(f"{deck} has {len(source_prs.slides)} slides; {number} is out of range")
        source = source_prs.slides[number - 1]
        slide = self.prs.slides.add_slide(self.layout(source.slide_layout.name, source.slide_layout))
        element = slide._element
        for child in list(element):
            element.remove(child)
        for child in source._element:
            element.append(copy.deepcopy(child))
        for key, value in source._element.attrib.items():
            element.set(key, value)
        mapping, dropped = {}, set()
        for rId, rel in source.part.rels.items():
            if rel.reltype in SKIP_RELS:
                continue
            if rel.reltype == RT.SLIDE:
                dropped.add(rId)  # links to other slides of the old deck cannot survive
            elif rel.is_external:
                mapping[rId] = slide.part.relate_to(rel.target_ref, rel.reltype, is_external=True)
            else:
                mapping[rId] = slide.part.relate_to(self.copy_part(rel.target_part, deck), rel.reltype)
        broken = []
        for node in element.iter():
            for attribute, value in list(node.attrib.items()):
                if attribute.startswith("{" + R_NS + "}"):
                    if value in dropped:
                        broken.append(node)
                    elif value in mapping:
                        node.set(attribute, mapping[value])
        for node in broken:
            node.getparent().remove(node)
        if source.has_notes_slide and source.notes_slide.notes_text_frame is not None \
                and source.notes_slide.notes_text_frame.text.strip():
            # Copy the notes paragraphs with their formatting; links in them pointed into the old deck.
            target = slide.notes_slide.notes_text_frame._txBody
            for paragraph in target.findall(qn("a:p")):
                target.remove(paragraph)
            for paragraph in source.notes_slide.notes_text_frame._txBody.findall(qn("a:p")):
                paragraph = copy.deepcopy(paragraph)
                for link in paragraph.iter(qn("a:hlinkClick"), qn("a:hlinkMouseOver")):
                    link.getparent().remove(link)
                target.append(paragraph)
        return slide

    def embed_fonts(self):
        """Carry fonts embedded in the source decks into the output."""
        output = self.prs.part._element
        existing = output.find(qn("p:embeddedFontLst"))
        names = {f.find(qn("p:font")).get("typeface") for f in existing} if existing is not None else set()
        for deck, source in self.sources.items():
            fonts = source.part._element.find(qn("p:embeddedFontLst"))
            for font in fonts if fonts is not None else []:
                face = font.find(qn("p:font")).get("typeface")
                if face in names:
                    continue
                font = copy.deepcopy(font)
                for variant in font:
                    rId = variant.get(qn("r:id"))
                    if rId:
                        rel = source.part.rels[rId]
                        variant.set(qn("r:id"), self.prs.part.relate_to(self.copy_part(rel.target_part, deck),
                                                                         rel.reltype))
                if existing is None:
                    existing = etree.Element(qn("p:embeddedFontLst"))
                    later = ("custShowLst", "photoAlbum", "custDataLst", "kinsoku", "defaultTextStyle",
                             "modifyVerifier", "extLst")
                    following = next((c for c in output if isinstance(c.tag, str)
                                      and etree.QName(c).localname in later), None)
                    if following is not None:
                        following.addprevious(existing)
                    else:
                        output.append(existing)
                existing.append(font)
                names.add(face)
                output.set("embedTrueTypeFonts", "1")
                self.warnings.append(f"embedded font '{face}' from {deck} was carried into the output")

    def from_layout(self, name):
        return self.prs.slides.add_slide(self.layout(name))


def find_shape(slide, key):
    shapes = [shape for shape, _ in walk_shapes(slide.shapes)]
    key = str(key)
    if key.isdigit():
        found = [s for s in shapes if s.shape_id == int(key)]
    elif key.startswith("ph:"):
        found = [s for s in shapes if s.is_placeholder and s.placeholder_format.idx == int(key[3:])]
    else:
        found = [s for s in shapes if s.name == key]
    if len(found) != 1:
        raise KeyError(f"shape '{key}' {'not found' if not found else 'is ambiguous'}")
    return found[0]


def paragraph_items(value):
    if isinstance(value, str):
        return [{"text": line, "level": 0} for line in value.split("\n")]
    items = []
    for item in value:
        if isinstance(item, str):
            items.append({"text": item, "level": 0})
        elif isinstance(item, dict) and isinstance(item.get("runs"), list):
            runs = item["runs"]
            if not all(isinstance(r, dict) and isinstance(r.get("text"), str) for r in runs):
                raise ValueError("runs are {text, style?, bold?}")
            items.append({"text": "".join(r["text"] for r in runs), "level": int(item.get("level", 0)),
                          "runs": runs})
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            items.append({"text": item["text"], "level": int(item.get("level", 0))})
        else:
            raise ValueError("paragraphs are strings, {text, level} or {runs: [{text, style}], level}")
    return items


def run_properties(paragraph, index, where):
    runs = paragraph.findall(qn("a:r"))
    if not 0 <= index < len(runs):
        raise ValueError(f"{where} has {len(runs)} runs; style {index} does not exist (see `show`)")
    properties = runs[index].find(qn("a:rPr"))
    return properties if properties is not None else etree.Element(qn("a:rPr"))


def set_text(frame, value):
    """Replace text while keeping each level's paragraph and run formatting.

    `**x**` makes bold. A paragraph given as runs can take each run's formatting from a run
    of the model: `style: R` is run R of the paragraph used for that level, `style: [P, R]`
    is run R of the model's paragraph P (indexes from `show`, starting at 0).
    """
    body = frame._txBody
    paragraphs = body.findall(qn("a:p"))
    prototypes = {}
    for paragraph in paragraphs:
        ppr = paragraph.find(qn("a:pPr"))
        prototypes.setdefault(int(ppr.get("lvl", "0")) if ppr is not None else 0, paragraph)
    fallback = paragraphs[0] if paragraphs else etree.SubElement(body, qn("a:p"))
    for paragraph in paragraphs:
        body.remove(paragraph)
    for item in paragraph_items(value):
        level = item["level"]
        lower = max([known for known in prototypes if known < level], default=None)
        prototype = prototypes[level] if level in prototypes else prototypes[lower] if lower is not None else fallback
        paragraph = copy.deepcopy(prototype)
        first_run = paragraph.find(qn("a:r"))
        end = paragraph.find(qn("a:endParaRPr"))
        properties = first_run.find(qn("a:rPr")) if first_run is not None else end
        for child in list(paragraph):
            if child.tag != qn("a:pPr"):
                paragraph.remove(child)
        ppr = paragraph.find(qn("a:pPr"))
        if level and (ppr is None or int(ppr.get("lvl", "0")) != level):
            if ppr is None:
                ppr = etree.SubElement(paragraph, qn("a:pPr"))
                paragraph.insert(0, ppr)
            ppr.set("lvl", str(level))
        if "runs" in item:
            segments = []
            for spec in item["runs"]:
                style = spec.get("style", 0)
                if isinstance(style, list) and len(style) == 2 and all(isinstance(i, int) for i in style):
                    if not 0 <= style[0] < len(paragraphs):
                        raise ValueError(f"the model has {len(paragraphs)} paragraphs; style {style} does not exist")
                    source = run_properties(paragraphs[style[0]], style[1], f"paragraph {style[0]}")
                elif isinstance(style, int):
                    source = run_properties(prototype, style, "the level's model paragraph")
                else:
                    raise ValueError("style is a run index R or [paragraph, run]")
                segments.append((spec["text"], source, spec.get("bold")))
        else:
            segments = [(segment, properties, True if index % 2 else None)
                        for index, segment in enumerate(re.split(r"\*\*", item["text"]))]
        for segment, source, bold in segments:
            if not segment:
                continue
            run = etree.SubElement(paragraph, qn("a:r"))
            rpr = copy.deepcopy(source) if source is not None else etree.Element(qn("a:rPr"))
            rpr.tag = qn("a:rPr")
            if bold is not None:
                rpr.set("b", "1" if bold else "0")
            run.append(rpr)
            etree.SubElement(run, qn("a:t")).text = segment
        if end is not None:
            paragraph.append(copy.deepcopy(end))
        body.append(paragraph)


def set_image(slide, shape, path):
    from PIL import Image
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if hasattr(shape, "insert_picture"):
        shape.insert_picture(str(path))
        return
    blip = shape._element.find(".//" + qn("a:blip"))
    if blip is None:
        raise ValueError(f"shape {shape.shape_id} is not a picture")
    _, rId = slide.part.get_or_add_image_part(str(path))
    blip.set(qn("r:embed"), rId)
    # Crop the new image to fill the existing frame without distortion.
    with Image.open(path) as image:
        ratio = image.width / image.height
    frame = shape.width / shape.height
    shape.crop_left = shape.crop_right = shape.crop_top = shape.crop_bottom = 0
    if ratio > frame:
        excess = (1 - frame / ratio) / 2
        shape.crop_left = shape.crop_right = excess
    elif ratio < frame:
        excess = (1 - ratio / frame) / 2
        shape.crop_top = shape.crop_bottom = excess


def set_table(shape, rows):
    if not getattr(shape, "has_table", False):
        raise ValueError(f"shape {shape.shape_id} is not a table")
    table = shape.table
    if any(len(row) > len(table.columns) for row in rows):
        raise ValueError(f"table {shape.shape_id} has {len(table.columns)} columns")
    element = table._tbl
    trs = element.findall(qn("a:tr"))
    while len(trs) < len(rows):
        clone = copy.deepcopy(trs[-1])
        trs[-1].addnext(clone)
        trs.append(clone)
    for extra in trs[len(rows):]:
        element.remove(extra)
    for row, values in zip(table.rows, rows, strict=False):
        for cell, value in zip(row.cells, list(values) + [""] * (len(table.columns) - len(values)), strict=False):
            set_text(cell.text_frame, str(value))


def set_chart(shape, spec):
    if not getattr(shape, "has_chart", False):
        raise ValueError(f"shape {shape.shape_id} is not a chart")
    data = CategoryChartData()
    data.categories = spec["categories"]
    for name, values in spec["series"].items():
        data.add_series(name, values)
    shape.chart.replace_data(data)


def apply_fill(slide, key, value):
    shape = find_shape(slide, key)
    if isinstance(value, dict) and "image" in value:
        set_image(slide, shape, value["image"])
    elif isinstance(value, dict) and "table" in value:
        set_table(shape, value["table"])
    elif isinstance(value, dict) and "chart" in value:
        set_chart(shape, value["chart"])
    elif isinstance(value, (str, list)):
        if not shape.has_text_frame:
            raise ValueError(f"shape {key} has no text")
        set_text(shape.text_frame, value)
    else:
        raise ValueError(f"unsupported fill for {key}: use text, paragraphs, image, table or chart")


# rPr children must keep the schema order when a font is added.
RPR_ORDER = ["ln", "noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill", "effectLst", "effectDag",
             "highlight", "uLnTx", "uLn", "uFillTx", "uFill", "latin", "ea", "cs", "sym", "hlinkClick",
             "hlinkMouseOver", "rtl", "extLst"]


def set_typeface(rpr, script, face):
    element = rpr.find(qn("a:" + script))
    if element is None:
        element = etree.Element(qn("a:" + script))
        later = RPR_ORDER[RPR_ORDER.index(script) + 1:]
        following = next((c for c in rpr if isinstance(c.tag, str) and etree.QName(c).localname in later), None)
        if following is not None:
            following.addprevious(element)
        else:
            rpr.append(element)
    element.set("typeface", face)


def pin_paragraphs(body, source, built):
    """Write the source's displayed font and size onto runs whose inherited values changed."""
    pinned = 0
    for element, before, after in zip(body.findall(qn("a:p")), source, built, strict=False):
        items = [item for item in element if isinstance(item.tag, str)
                 and etree.QName(item).localname in ("r", "fld", "br", "AlternateContent")]
        for item, old, new in zip(items, before["runs"], after["runs"], strict=False):
            if etree.QName(item).localname not in ("r", "fld"):
                continue
            changes = {k: old[k] for k in ("latin", "ea", "size") if old.get(k) and old.get(k) != new.get(k)}
            if not changes:
                continue
            rpr = item.find(qn("a:rPr"))
            if rpr is None:
                rpr = etree.Element(qn("a:rPr"))
                item.insert(0, rpr)
            for script in ("latin", "ea"):
                if script in changes:
                    set_typeface(rpr, script, changes[script])
            if "size" in changes:
                rpr.set("sz", str(round(changes["size"] * 100)))
            pinned += 1
    return pinned


def pin_fonts(slide, source, built):
    """Keep a cloned slide's look when its deck's theme or master differs from the template."""
    built_shapes = {s["id"]: s for s in flatten(built["shapes"])}
    elements = {shape.shape_id: shape for shape, _ in walk_shapes(slide.shapes)}
    pinned = 0
    for old in flatten(source["shapes"]):
        new, shape = built_shapes.get(old["id"]), elements.get(old["id"])
        if new is None or shape is None:
            continue
        if old.get("text") and new.get("text"):
            body = shape._element.find(qn("p:txBody"))
            pinned += pin_paragraphs(body, old["text"]["paragraphs"], new["text"]["paragraphs"])
        if old.get("table") and new.get("table") and getattr(shape, "has_table", False):
            for row, before, after in zip(shape.table._tbl.findall(qn("a:tr")), old["table"]["rows"],
                                          new["table"]["rows"], strict=False):
                for cell, a, b in zip(row.findall(qn("a:tc")), before["cells"], after["cells"], strict=False):
                    if a.get("paragraphs") and b.get("paragraphs"):
                        pinned += pin_paragraphs(cell.find(qn("a:txBody")), a["paragraphs"], b["paragraphs"])
    if (source.get("notes") or {}).get("paragraphs") and (built.get("notes") or {}).get("paragraphs"):
        pinned += pin_paragraphs(slide.notes_slide.notes_text_frame._txBody, source["notes"]["paragraphs"],
                                 built["notes"]["paragraphs"])
    return pinned


def build(library, plan, out):
    builder = Builder(library)
    specs = plan.get("slides")
    if not isinstance(specs, list) or not specs:
        fail("plan.slides must be a non-empty list")
    for index, spec in enumerate(specs, 1):
        if "from" in spec:
            deck, _, number = str(spec["from"]).rpartition(":")
            if not deck or not number.isdigit():
                fail(f"slide {index}: 'from' is DECK:NUMBER")
            builder.clone(deck, int(number))
        elif "layout" in spec:
            builder.from_layout(spec["layout"])
        else:
            fail(f"slide {index}: give 'from' (a past slide) or 'layout' (a template layout)")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    builder.embed_fonts()
    builder.prs.save(out)
    # Reopen so copied charts load as chart parts before they are filled.
    prs = Presentation(out)
    built = ooxml.extract(out)
    errors = []
    for index, (slide, spec) in enumerate(zip(prs.slides, specs, strict=True), 1):
        if "from" in spec:
            deck, _, number = str(spec["from"]).rpartition(":")
            pinned = pin_fonts(slide, library.slide(spec["from"]), built["slides"][index - 1])
            if pinned:
                builder.warnings.append(
                    f"slide {index} (from {spec['from']}): its deck's theme or master differs from the template, "
                    f"so {pinned} text runs would have changed font or size; their original font and size were "
                    "written onto them to keep the look")
        try:
            for key in spec.get("delete", []):
                shape = find_shape(slide, key)
                shape._element.getparent().remove(shape._element)
            for key, value in spec.get("fill", {}).items():
                apply_fill(slide, key, value)
            if "notes" in spec:
                # Notes take the same text forms as shapes and keep the model's notes formatting.
                set_text(slide.notes_slide.notes_text_frame, spec["notes"])
        except (KeyError, ValueError, FileNotFoundError) as error:
            errors.append(f"slide {index}: {error}")
    if errors:
        fail("\n".join(errors))
    prs.save(out)
    return builder.warnings


# ---------------------------------------------------------------- checks


def text_width(text, size):
    return sum(size if unicodedata.east_asian_width(c) in "WFA" else size * 0.5 for c in text)


def spacing(value, size):
    if not value:
        return 0.0
    number = float(value[:-2] if value.endswith("pt") else value[:-1])
    return number if value.endswith("pt") else size * 1.2 * number / 100


def overflow(shape):
    box, text = shape.get("box"), shape.get("text")
    if not box or not text:
        return None
    left, top, right, bottom = text["body"].get("insets_pt", [7.2, 3.6, 7.2, 3.6])
    width, height = box["w"] - left - right, box["h"] - top - bottom
    if width <= 0 or height <= 0:
        return None
    # Shrink-on-overflow stores the scale PowerPoint applied.
    scale = text["body"].get("font_scale", 100) / 100
    reduction = text["body"].get("line_reduction", 0) / 100
    needed = 0.0
    for paragraph in text["paragraphs"]:
        sizes = [r["size"] for r in paragraph["runs"] if r.get("size")] or \
            [paragraph.get("empty_run_format", {}).get("size") or 18]
        size = max(sizes) * scale
        fmt = paragraph["format"]
        indent = (fmt.get("margin_left_pt") or 0) + max(0, fmt.get("indent_pt") or 0)
        lines = sum(max(1, math.ceil(text_width(part, size) / max(1.0, width - indent)))
                    for part in run_text(paragraph).split("\n"))
        line_height = size * 1.2
        if fmt.get("lnSpc"):
            line_height = spacing(fmt["lnSpc"], size) if fmt["lnSpc"].endswith("pt") else \
                size * 1.2 * float(fmt["lnSpc"][:-1]) / 100
        line_height *= 1 - reduction
        needed += lines * line_height + spacing(fmt.get("spcBef"), size) + spacing(fmt.get("spcAft"), size)
    return {"needed": round(needed), "available": round(height), "autofit": text["body"].get("autofit"),
            "ratio": needed / height}


def corpus_facts(models):
    fonts, colors, sizes, chars, ratios = set(), set(), [], [], []
    for model in models.values():
        for master in model.get("masters", {}).values():
            for kind in master["theme"]["fonts"].values():
                fonts.update(f for k, f in kind.items() if k != "scripts" and f)
        for slide in model["slides"]:
            chars.append(sum(len(p["text"]) for s in body_shapes(slide) for p in s["text"]["paragraphs"]))
            for shape in flatten(slide["shapes"]):
                fit = overflow(shape) if shape.get("text") else None
                if fit and fit["autofit"] != "spAutoFit" and any(r for _, r in visible_runs(shape)):
                    ratios.append(fit["ratio"])
                for _, run in visible_runs(shape):
                    fonts.update(run[k] for k in ("latin", "ea") if run.get(k))
                    if (run.get("color") or {}).get("rgb"):
                        colors.add(run["color"]["rgb"])
                    if run.get("size"):
                        sizes.append(run["size"])
    sizes.sort()
    chars.sort()
    ratios.sort()
    # The estimate is calibrated on the user's own slides, which are known to fit.
    tolerance = max(1.05, ratios[int(0.98 * (len(ratios) - 1))] * 1.05) if ratios else 1.05
    return {"fonts": fonts, "colors": colors, "fit_tolerance": round(tolerance, 2),
            "smallest": sizes[max(0, int(len(sizes) * 0.02) - 1)] if sizes else None,
            "densest": chars[int(0.95 * (len(chars) - 1))] if chars else None}


def check(library, path):
    model = ooxml.extract(path)
    facts = corpus_facts(library.models()) if library else {"fonts": set(), "colors": set(), "fit_tolerance": 1.05,
                                                             "smallest": None, "densest": None}
    width, height = model["size"]
    issues = []

    def add(number, severity, message):
        issue = {"slide": number, "severity": severity, "message": message}
        if issue not in issues:
            issues.append(issue)

    for slide in model["slides"]:
        number, total = slide["number"], 0
        for shape in flatten(slide["shapes"]):
            label = f"shape {shape['id']} '{shape['name']}'"
            box = shape.get("box")
            if box and (box["x"] < -1 or box["y"] < -1 or box["x"] + box["w"] > width + 1
                        or box["y"] + box["h"] > height + 1):
                add(number, "warn", f"{label} extends beyond the slide")
            kind = placeholder_kind(shape)
            if kind and kind not in META_KINDS and shape["kind"] == "shape" and not any(
                    p["text"].strip() for p in (shape.get("text") or {}).get("paragraphs", [])):
                add(number, "error", f"{label} is an empty placeholder; fill it or delete it")
            if shape["kind"] == "picture" and (shape.get("image") or {}).get("pixels") and box \
                    and not shape["image"].get("svg"):
                crop = shape.get("crop", {})
                w, h = shape["image"]["pixels"]
                visible_w = w * (1 - (crop.get("l", 0) + crop.get("r", 0)) / 100)
                visible_h = h * (1 - (crop.get("t", 0) + crop.get("b", 0)) / 100)
                if visible_h > 0 and box["h"] > 0 and abs((visible_w / visible_h) / (box["w"] / box["h"]) - 1) > 0.03:
                    add(number, "warn", f"{label} is stretched (aspect ratio differs by more than 3%)")
            texts = [p["text"] for p in (shape.get("text") or {}).get("paragraphs", [])]
            texts += [c.get("text", "") for row in (shape.get("table") or {}).get("rows", []) for c in row["cells"]]
            for text in texts:
                if LEFTOVER.search(text):
                    add(number, "error", f"{label} contains placeholder text: {LEFTOVER.search(text).group(0)!r}")
            if not shape.get("text"):
                continue
            if not is_title(shape, slide) and kind not in META_KINDS:
                total += sum(len(p["text"]) for p in shape["text"]["paragraphs"])
            fit = overflow(shape) if any(t.strip() for t in texts) else None
            if fit and fit["autofit"] == "spAutoFit":
                # The shape grows with its text; only growing past the slide's bottom is a problem.
                grown = box["y"] + fit["needed"] / facts["fit_tolerance"] + (box["h"] - fit["available"])
                if grown > height + 1:
                    add(number, "warn", f"{label} grows to fit its text and likely runs past the bottom of the slide")
            elif fit and fit["ratio"] > facts["fit_tolerance"]:
                severity = "warn" if fit["autofit"] == "normAutofit" else "error"
                add(number, severity, f"{label} likely overflows: needs ~{fit['needed']}pt of {fit['available']}pt "
                                      f"height, more than any of your past slides (autofit={fit['autofit']}); "
                                      "confirm in the render")
            for _, run in visible_runs(shape):
                if facts["smallest"] and run.get("size") and run["size"] < facts["smallest"]:
                    add(number, "warn", f"{label} uses {run['size']:g}pt, smaller than your decks use")
                for key in ("latin", "ea"):
                    if facts["fonts"] and run.get(key) and run[key] not in facts["fonts"]:
                        add(number, "warn", f"{label} uses font {run[key]} not found in your decks")
                rgb = (run.get("color") or {}).get("rgb")
                if facts["colors"] and rgb and rgb not in facts["colors"]:
                    add(number, "info", f"{label} uses text color {rgb} not found in your decks")
        notes = (slide.get("notes") or {}).get("text", "")
        if LEFTOVER.search(notes):
            add(number, "error", f"speaker notes contain placeholder text: {LEFTOVER.search(notes).group(0)!r}")
        if facts["densest"] is not None and total > facts["densest"]:
            add(number, "warn", f"{total} body characters; denser than 95% of your past slides ({facts['densest']})")
    return {"slides": len(model["slides"]), "issues": issues}



# ---------------------------------------------------------------- commands


def command_ingest(args):
    library = Library(args.library, create=True)
    if args.template:
        template = Path(args.template)
        if template.suffix.lower() not in (".pptx", ".potx"):
            fail("the template must be .pptx or .potx (convert .ppt first)")
        shutil.copyfile(template, library.root / "template.pptx")
        library.meta["template"] = "template.pptx"
        library.meta["template_source"] = str(template.resolve())
    files = []
    for item in args.decks:
        item = Path(item)
        files += sorted(item.rglob("*.pptx")) if item.is_dir() else [item]
    skipped = [f for f in files if f.name.startswith("~$")]
    files = [f for f in files if f not in skipped]
    known = {entry["sha256"]: deck for deck, entry in library.meta["decks"].items()}
    added = []
    for path in files:
        if path.suffix.lower() != ".pptx":
            print(f"[skip] {path}: only .pptx is read (convert .ppt/.key first)")
            continue
        digest = sha256(path)
        if digest in known:
            continue
        deck = deck_id(path, digest)
        target = library.root / "decks" / f"{deck}.pptx"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        library.meta["decks"][deck] = {"file": f"decks/{deck}.pptx", "sha256": digest,
                                       "source": str(path.resolve()), "added": time.strftime("%Y-%m-%d")}
        known[digest] = deck
        added.append(deck)
    # Decks read by an older reader are read again, so improvements reach the whole library.
    stale = [deck for deck in library.meta["decks"] if args.reextract or deck in added or
             (read_json(library.model_path(deck)) or {}).get("model_version") != ooxml.MODEL_VERSION]
    for deck in stale:
        try:
            model = ooxml.extract(library.deck_path(deck))
        except Exception as error:  # noqa: BLE001 -- one unreadable deck must not stop the library
            print(f"[fail] {deck}: {error}")
            library.meta["decks"].pop(deck)
            library.deck_path_unchecked(deck).unlink(missing_ok=True)
            if deck in added:
                added.remove(deck)
            continue
        write_json(library.model_path(deck), model)
        (library.root / "text").mkdir(exist_ok=True)
        (library.root / "text" / f"{deck}.md").write_text(text_markdown(deck, model))
        leftovers = sum(len(s["uninterpreted"]) for s in model["slides"])
        print(f"[{'added' if deck in added else 'reread'}] {deck}: {len(model['slides'])} slides"
              + (f", {leftovers} uninterpreted XML elements kept in the model" if leftovers else ""))
    library.save()
    if library.meta.get("template"):
        write_json(library.root / "template-model.json", ooxml.extract(library.template))
    (library.root / "stats.md").write_text(statistics_markdown(library.models()))
    for name in ("roles.json",):
        if not (library.root / name).exists():
            write_json(library.root / name, {})
    if not args.no_render:
        targets = [(deck, library.deck_path(deck)) for deck in (library.meta["decks"] if args.rerender else added)]
        if library.meta.get("template") and (args.rerender or args.template):
            targets.append(("template", library.template))
        if targets and office() is None:
            print("[warn] LibreOffice is not installed; thumbnails were not rendered (see `doctor`)")
        elif targets:
            for deck, path in targets:
                try:
                    render(path, library.root / "renders" / deck, dpi=args.dpi,
                           font_dirs=[library.root / "fonts"], label=deck)
                    print(f"[render] {deck}: renders/{deck}/grid.png")
                except (RuntimeError, subprocess.SubprocessError) as error:
                    print(f"[warn] {deck}: render failed: {error}")
    print(f"library: {library.root} ({len(library.meta['decks'])} decks, {len(skipped)} lock files skipped)")
    print("next: read stats.md, text/*.md and renders/*/grid.png, then write style-profile.md and roles.json")


def command_find(args):
    library = Library(args.library)
    roles = library.roles()
    results = []
    for deck, model in library.models().items():
        for slide in model["slides"]:
            key = f"{deck}:{slide['number']}"
            role = roles.get(key, {})
            text = slide_text(slide)
            kinds = {s["kind"] for s in flatten(slide["shapes"])}
            if any(r.get("math") for s in flatten(slide["shapes"]) for _, r in visible_runs(s)):
                kinds.add("equation")
            if args.role and args.role.casefold() not in str(role.get("role", "")).casefold():
                continue
            if args.layout and args.layout.casefold() not in slide["layout"].casefold():
                continue
            if args.has and not set(args.has) <= kinds:
                continue
            if args.text and not all(word.casefold() in text.casefold() for word in args.text):
                continue
            if args.exemplary and not role.get("exemplary"):
                continue
            image = library.root / "renders" / deck / f"slide-{slide['number']}.png"
            results.append({"slide": key, "layout": slide["layout"], "title": slide_title(slide),
                            "role": role.get("role"), "note": role.get("note"),
                            "contains": sorted(kinds - {"shape"}),
                            "image": str(image) if image.exists() else None})
    print(json.dumps(results[: args.limit], ensure_ascii=False, indent=1))
    if len(results) > args.limit:
        print(f"... {len(results) - args.limit} more; narrow with --role/--text/--layout/--has", file=sys.stderr)


def command_show(args):
    library = Library(args.library)
    slide = library.slide(args.slide)
    deck = args.slide.rpartition(":")[0]
    image = library.root / "renders" / deck / f"slide-{slide['number']}.png"
    print(json.dumps(dict(slide, slide=args.slide, image=str(image) if image.exists() else None,
                          role=library.roles().get(args.slide)), ensure_ascii=False, indent=1))


def command_raw(args):
    if args.slide and ":" in args.slide and not args.slide.endswith(".pptx"):
        library = Library(args.library)
        deck, _, number = args.slide.rpartition(":")
        path, number = library.deck_path(deck), int(number)
    else:
        path, number = Path(args.slide or args.file), args.number
    for name, xml in ooxml.raw_parts(path, number, args.part).items():
        print(f"===== {name}")
        print(xml)


def command_layouts(args):
    library = Library(args.library)
    prs = Presentation(library.template)
    for master_number, master in enumerate(prs.slide_masters, 1):
        for layout in master.slide_layouts:
            placeholders = [f"ph:{p.placeholder_format.idx}={p.placeholder_format.type.name.lower()}"
                            f" '{p.name}'" for p in layout.placeholders]
            print(f"[master {master_number}] {layout.name}: {', '.join(placeholders) or '(no placeholders)'}")


def command_build(args):
    library = Library(args.library)
    plan = read_json(args.plan)
    if plan is None:
        fail(f"plan not found: {args.plan}")
    base = Path(args.plan).resolve().parent
    for spec in plan.get("slides", []):
        for value in spec.get("fill", {}).values():
            if isinstance(value, dict) and "image" in value and not Path(value["image"]).is_absolute():
                value["image"] = str(base / value["image"])
    warnings = build(library, plan, args.out)
    for warning in warnings:
        print("[warn] " + warning)
    print(f"built {args.out}")
    report = check(library, args.out)
    print_check(report)
    rendered = None if args.no_render else render_output(library, args.out, args.dpi)
    # A report next to the deck keeps what the user must be told after the session ends.
    out = Path(args.out)
    lines = [f"# Build report: {out.name}", "", f"- Built: {time.strftime('%Y-%m-%d %H:%M')}",
             f"- Plan: {Path(args.plan).resolve()}", f"- Slides: {report['slides']}",
             f"- Render: {rendered or 'not rendered'}", "", "## Build notices", ""]
    lines += [f"- {w}" for w in warnings] or ["- none"]
    lines += ["", "## Check", ""]
    lines += [f"- [{i['severity']}] slide {i['slide']}: {i['message']}" for i in report["issues"]] or ["- no issues"]
    path = out.with_name(out.stem + "-report.md")
    path.write_text("\n".join(lines) + "\n")
    print(f"report: {path}")


def render_output(library, pptx, dpi):
    target = Path(pptx).with_suffix("")
    target = target.parent / (target.name + "-render")
    try:
        images = render(pptx, target, dpi=dpi, font_dirs=[library.root / "fonts"] if library else [])
    except (RuntimeError, subprocess.SubprocessError) as error:
        print(f"[warn] not rendered: {error}")
        return None
    print(f"rendered {len(images)} slides to {target}/ (grid.png, slide-N.png); inspect every slide image")
    return str(target)


def print_check(report):
    counts = {}
    for issue in report["issues"]:
        counts[issue["severity"]] = counts.get(issue["severity"], 0) + 1
        print(f"[{issue['severity']}] slide {issue['slide']}: {issue['message']}")
    print(f"check: {report['slides']} slides, " + (", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
                                                   or "no issues"))


def command_check(args):
    library = Library(args.library) if args.library else None
    report = check(library, args.pptx)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print_check(report)
    sys.exit(1 if any(i["severity"] == "error" for i in report["issues"]) else 0)


def command_render(args):
    library = Library(args.library) if args.library else None
    out = args.out or (Path(args.pptx).with_suffix("").as_posix() + "-render")
    images = render(args.pptx, out, dpi=args.dpi,
                    font_dirs=([library.root / "fonts"] if library else []) + (args.fonts or []))
    print(f"rendered {len(images)} slides to {out}/")


def command_doctor(args):
    ok = True
    print(f"[ok] python-pptx and Pillow (python {sys.version.split()[0]})")
    for name, binary in (("LibreOffice", office()), ("pdftoppm", shutil.which("pdftoppm"))):
        print(f"[{'ok' if binary else 'missing'}] {name}: {binary or 'needed for slide images'}")
        ok &= bool(binary)
    if args.library:
        library = Library(args.library)
        faces = set()
        corpus_fonts = corpus_facts(library.models())["fonts"]
        env = dict(os.environ)
        with tempfile.TemporaryDirectory() as scratch:
            env.update(font_config([library.root / "fonts"], scratch))
            for face in sorted(faces | corpus_fonts):
                if face.startswith("+"):
                    continue
                try:
                    match = subprocess.run(["fc-match", "-f", "%{family}", face], capture_output=True,
                                           text=True, timeout=10, env=env).stdout
                except (OSError, subprocess.SubprocessError):
                    print("[warn] fc-match is unavailable; fonts were not checked")
                    break
                found = face.casefold() in match.casefold()
                print(f"[{'ok' if found else 'substituted'}] font {face}" + ("" if found else f" -> {match}"))
        print(f"note: put licensed font files in {library.root / 'fonts'} to render with the real fonts")
    sys.exit(0 if ok else 1)


def main():
    # The library lives outside the read-only skill; PERSONAL_SLIDES_LIBRARY names the usual one.
    default = os.environ.get("PERSONAL_SLIDES_LIBRARY")
    global LIBRARY
    LIBRARY = {"default": default} if default else {"required": True}
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="check renderers and fonts")
    doctor.add_argument("--library", default=default)
    ingest = sub.add_parser("ingest", help="add the template and past decks to a library")
    ingest.add_argument("--library", **LIBRARY)
    ingest.add_argument("--template")
    ingest.add_argument("decks", nargs="*", help=".pptx files or folders searched recursively")
    ingest.add_argument("--no-render", action="store_true")
    ingest.add_argument("--rerender", action="store_true", help="render every deck again")
    ingest.add_argument("--reextract", action="store_true", help="read every deck's XML again")
    ingest.add_argument("--dpi", type=int, default=60)
    find = sub.add_parser("find", help="search past slides to reuse")
    find.add_argument("--library", **LIBRARY)
    find.add_argument("--role")
    find.add_argument("--layout")
    find.add_argument("--text", nargs="+")
    find.add_argument("--has", nargs="+", choices=["picture", "table", "chart", "group"])
    find.add_argument("--exemplary", action="store_true")
    find.add_argument("--limit", type=int, default=30)
    show = sub.add_parser("show", help="list a past slide's shapes (fill keys) and image")
    show.add_argument("--library", **LIBRARY)
    show.add_argument("slide", help="DECK:NUMBER")
    raw = sub.add_parser("raw", help="print the untouched XML of a slide and the parts it uses")
    raw.add_argument("--library", **LIBRARY)
    raw.add_argument("slide", nargs="?", help="DECK:NUMBER from the library")
    raw.add_argument("--file", help="any .pptx instead of a library slide")
    raw.add_argument("--number", type=int, help="slide number with --file")
    raw.add_argument("--part", nargs="+", help="part names such as ppt/slideMasters/slideMaster1.xml")
    layouts = sub.add_parser("layouts", help="list the template's layouts and placeholders")
    layouts.add_argument("--library", **LIBRARY)
    build_parser = sub.add_parser("build", help="build a deck from a plan JSON")
    build_parser.add_argument("--library", **LIBRARY)
    build_parser.add_argument("--plan", required=True)
    build_parser.add_argument("--out", required=True)
    build_parser.add_argument("--no-render", action="store_true")
    build_parser.add_argument("--dpi", type=int, default=110)
    check_parser = sub.add_parser("check", help="lint a deck against the library")
    check_parser.add_argument("pptx")
    check_parser.add_argument("--library", default=default)
    check_parser.add_argument("--json", action="store_true")
    render_parser = sub.add_parser("render", help="render slides to PNG")
    render_parser.add_argument("pptx")
    render_parser.add_argument("--out")
    render_parser.add_argument("--library", default=default)
    render_parser.add_argument("--fonts", nargs="+")
    render_parser.add_argument("--dpi", type=int, default=110)
    args = parser.parse_args()
    {"doctor": command_doctor, "ingest": command_ingest, "find": command_find, "show": command_show,
     "layouts": command_layouts, "raw": command_raw, "build": command_build, "check": command_check,
     "render": command_render}[args.command](args)


if __name__ == "__main__":
    main()
