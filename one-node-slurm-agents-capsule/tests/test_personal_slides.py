"""personal-slides: learn from synthetic past decks and rebuild slides from them."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SLIDES = ROOT / "common/skills/personal-slides/scripts/slides"
UV = ["uv", "run", "--no-project", "--quiet", "--with", "python-pptx==1.0.2", "--with", "pillow==11.3.0", "python"]

FIXTURES = textwrap.dedent("""
    import sys
    from pathlib import Path
    from PIL import Image
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches, Pt

    root = Path(sys.argv[1])
    Image.new("RGB", (400, 200), "navy").save(root / "wide.png")
    Image.new("RGB", (300, 300), "orange").save(root / "square.png")
    template = Presentation()
    template.slide_width, template.slide_height = Inches(13.333), Inches(7.5)
    template.slides.add_slide(template.slide_layouts[0]).shapes.title.text = "TEMPLATE SAMPLE"
    template.save(root / "template.pptx")

    deck = Presentation(root / "template.pptx")
    first = deck.slides[0]
    first.shapes.title.text = "研究の背景"
    body = deck.slides.add_slide(deck.slide_layouts[1])
    body.shapes.title.text = "提案手法の要点"
    frame = body.placeholders[1].text_frame
    frame.text = "既存手法は長い系列で精度が落ちる"
    run = frame.paragraphs[0].runs[0]
    run.font.size, run.font.bold, run.font.color.rgb = Pt(20), False, RGBColor(0x1E, 0x27, 0x61)
    code = frame.paragraphs[0].add_run()
    code.text, code.font.name, code.font.size = " (O(n^2))", "Consolas", Pt(20)
    sub = frame.add_paragraph()
    sub.text, sub.level = "注意機構の計算量が二乗で増える", 1
    sub.runs[0].font.size = Pt(16)
    body.notes_slide.notes_text_frame.text = "ここで課題を強調する"
    figure = deck.slides.add_slide(deck.slide_layouts[5])
    figure.shapes.title.text = "結果"
    figure.shapes.add_picture(str(root / "wide.png"), Inches(1), Inches(2), Inches(6), Inches(3))
    rows = figure.shapes.add_table(2, 2, Inches(7.5), Inches(2), Inches(5), Inches(1.5)).table
    for r, row in enumerate([["手法", "精度"], ["提案", "0.91"]]):
        for c, value in enumerate(row):
            rows.cell(r, c).text = value
    data = CategoryChartData()
    data.categories = ["A", "B"]
    data.add_series("精度", (0.8, 0.9))
    figure.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(7.5), Inches(4), Inches(5), Inches(3), data)
    link = figure.shapes.add_textbox(Inches(1), Inches(6), Inches(3), Inches(0.5))
    link.text_frame.text = "背景へ戻る"
    link.click_action.target_slide = first
    from lxml import etree
    box = body.shapes.add_textbox(Inches(1), Inches(6), Inches(4), Inches(0.6))
    box.text_frame.text = "x"
    paragraph = box.text_frame.paragraphs[0]._p
    for run in paragraph.findall("{http://schemas.openxmlformats.org/drawingml/2006/main}r"):
        paragraph.remove(run)
    M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    A14 = "http://schemas.microsoft.com/office/drawing/2010/main"
    MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
    alternate = etree.SubElement(paragraph, f"{{{MC}}}AlternateContent")
    choice = etree.SubElement(alternate, f"{{{MC}}}Choice", Requires="a14", nsmap={"a14": A14})
    math = etree.SubElement(etree.SubElement(etree.SubElement(choice, f"{{{A14}}}m"), f"{{{M}}}oMathPara"),
                            f"{{{M}}}oMath")
    fraction = etree.SubElement(math, f"{{{M}}}f")
    for part, value in (("num", "a"), ("den", "b")):
        etree.SubElement(etree.SubElement(etree.SubElement(fraction, f"{{{M}}}{part}"), f"{{{M}}}r"),
                         f"{{{M}}}t").text = value
    (root / "decks").mkdir()
    deck.save(root / "decks" / "talk 2025.pptx")
    (root / "decks" / "~$talk 2025.pptx").write_bytes(b"lock")

    # A deck made with another theme (Georgia) that embeds its font.
    import zipfile
    other = Presentation(root / "template.pptx")
    other.slides[0].shapes.title.text = "別テーマの表紙"
    box = other.slides[0].shapes.add_textbox(Inches(1), Inches(5), Inches(6), Inches(1))
    box.text_frame.text = "テーマのフォントを受け継ぐ文"
    other.save(root / "other-src.pptx")
    with zipfile.ZipFile(root / "other-src.pptx") as source, zipfile.ZipFile(root / "other.pptx", "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "ppt/theme/theme1.xml":
                data = data.replace(b'typeface="Calibri"', b'typeface="Georgia"')
            if item.filename == "[Content_Types].xml":
                data = data.replace(b"<Default ", b'<Default Extension="fntdata" ContentType="application/x-fontdata"/><Default ', 1)
            if item.filename == "ppt/_rels/presentation.xml.rels":
                data = data.replace(b"</Relationships>", b'<Relationship Id="rIdF1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/font" Target="fonts/font1.fntdata"/></Relationships>')
            if item.filename == "ppt/presentation.xml":
                data = data.replace(b"<p:defaultTextStyle>", b'<p:embeddedFontLst><p:embeddedFont><p:font typeface="Georgia"/><p:regular r:id="rIdF1"/></p:embeddedFont></p:embeddedFontLst><p:defaultTextStyle>')
            target.writestr(item, data)
        target.writestr("ppt/fonts/font1.fntdata", b"FAKEFONTDATA")
""")

INSPECT = textwrap.dedent("""
    import json, sys
    from pptx import Presentation
    prs = Presentation(sys.argv[1])
    out = []
    for slide in prs.slides:
        item = {"layout": slide.slide_layout.name, "texts": [], "pictures": 0, "chart": None, "table": None,
                "notes": slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""}
        for shape in slide.shapes:
            if shape.has_text_frame:
                item["texts"].append([(p.text, p.level, [r.font.size.pt if r.font.size else None for r in p.runs],
                                       [r.font.bold for r in p.runs]) for p in shape.text_frame.paragraphs])
            if shape.shape_type == 13:
                item["pictures"] += 1
                item["crop"] = [round(shape.crop_top, 3), round(shape.crop_bottom, 3)]
            if shape.has_chart:
                item["chart"] = [list(s.values) for s in shape.chart.plots[0].series]
            if shape.has_table:
                item["table"] = [[c.text for c in r.cells] for r in shape.table.rows]
        out.append(item)
    print(json.dumps(out, ensure_ascii=False))
""")


@unittest.skipUnless(shutil.which("uv"), "Requires uv to provide python-pptx")
class PersonalSlidesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        try:
            subprocess.run([*UV, "-c", FIXTURES, str(cls.root)], check=True, capture_output=True, timeout=300)
        except subprocess.SubprocessError as error:
            raise unittest.SkipTest(f"python-pptx is unavailable: {error}") from error
        cls.library = cls.root / "library"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def slides(self, *args, check=True):
        result = subprocess.run([str(SLIDES), *map(str, args)], capture_output=True, text=True, timeout=300)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def inspect(self, path):
        result = subprocess.run([*UV, "-c", INSPECT, str(path)], capture_output=True, text=True, timeout=300,
                                check=True)
        return json.loads(result.stdout)

    def ingest(self):
        if not (self.library / "corpus.json").exists():
            self.slides("ingest", "--library", self.library, "--template", self.root / "template.pptx",
                        self.root / "decks", "--no-render")
        return json.loads((self.library / "library.json").read_text())

    def test_ingest_records_style_evidence_once(self):
        meta = self.ingest()
        self.assertEqual(len(meta["decks"]), 1)  # the Office lock file is skipped
        deck = next(iter(meta["decks"]))
        stats = (self.library / "stats.md").read_text()
        self.assertIn("Body paragraphs per slide", stats)
        self.assertIn("#1E2761", stats)
        text = (self.library / "text" / f"{deck}.md").read_text()
        self.assertIn("  - (obj) 注意機構の計算量が二乗で増える", text)
        self.assertIn("> ここで課題を強調する", text)
        self.assertIn("(rect) $\\frac{a}{b}$", text)  # an equation inside mc:AlternateContent is read
        model = json.loads((self.library / "model" / f"{deck}.json").read_text())
        title = model["slides"][1]["shapes"][0]["text"]["paragraphs"][0]["runs"][0]
        self.assertEqual(title["size"], 44.0)  # inherited from the master title style
        self.assertEqual(title["latin"], "Calibri")  # +mj-lt resolved through the theme
        raw = self.slides("raw", "--library", self.library, f"{deck}:2").stdout
        self.assertIn("===== ppt/slides/slide2.xml", raw)
        self.assertIn(":oMath>", raw)
        again = self.slides("ingest", "--library", self.library, self.root / "decks", "--no-render").stdout
        self.assertNotIn("[added]", again)

    def test_find_and_show_expose_reusable_slides(self):
        deck = next(iter(self.ingest()["decks"]))
        (self.library / "roles.json").write_text(json.dumps({f"{deck}:3": {"role": "result", "exemplary": True}}))
        found = json.loads(self.slides("find", "--library", self.library, "--role", "result", "--has", "chart").stdout)
        self.assertEqual([item["slide"] for item in found], [f"{deck}:3"])
        shown = json.loads(self.slides("show", "--library", self.library, f"{deck}:2").stdout)
        kinds = {s["placeholder"]["type"] for s in shown["shapes"] if s.get("placeholder")}
        self.assertEqual(kinds, {"title", "obj"})
        layouts = self.slides("layouts", "--library", self.library).stdout
        self.assertIn("Title and Content: ph:0=title", layouts)

    def test_build_reuses_past_slides_with_their_formatting(self):
        deck = next(iter(self.ingest()["decks"]))
        shapes = json.loads(self.slides("show", "--library", self.library, f"{deck}:3").stdout)["shapes"]
        ids = {s["kind"]: s["id"] for s in shapes}
        plan = {"slides": [
            {"from": f"{deck}:2", "fill": {"ph:0": "新しい主張", "ph:1": [
                "長い系列でも **精度を保つ**", {"text": "計算量は線形", "level": 1}]}, "notes": ["新しいノート", "補足"]},
            {"from": f"{deck}:3", "fill": {
                str(ids["picture"]): {"image": "square.png"},
                str(ids["table"]): {"table": [["手法", "精度"], ["提案", "0.95"], ["従来", "0.88"]]},
                str(ids["chart"]): {"chart": {"categories": ["A", "B"], "series": {"精度": [0.7, 0.95]}}}}},
            {"layout": "Title Only", "fill": {"ph:0": "まとめ"}},
        ]}
        (self.root / "plan.json").write_text(json.dumps(plan, ensure_ascii=False))
        out = self.root / "out" / "talk.pptx"
        result = self.slides("build", "--library", self.library, "--plan", self.root / "plan.json",
                             "--out", out, "--no-render")
        self.assertIn("check: 3 slides", result.stdout)
        slides = self.inspect(out)
        self.assertEqual([s["layout"] for s in slides], ["Title and Content", "Title Only", "Title Only"])
        body = slides[0]["texts"][1]
        self.assertEqual([(p[0], p[1]) for p in body], [("長い系列でも 精度を保つ", 0), ("計算量は線形", 1)])
        self.assertEqual(body[0][2], [20.0, 20.0])  # the past slide's run size is kept
        self.assertEqual(body[0][3], [False, True])
        self.assertEqual(body[1][2], [16.0])
        self.assertEqual(slides[0]["notes"], "新しいノート\n補足")
        self.assertEqual(slides[1]["pictures"], 1)
        self.assertGreater(slides[1]["crop"][0], 0)  # a square image is cropped to the wide frame
        self.assertEqual(slides[1]["table"][2], ["従来", "0.88"])
        self.assertEqual(slides[1]["chart"], [[0.7, 0.95]])
        with zipfile.ZipFile(out) as archive:
            names = set(archive.namelist())
            for name in names:
                if name.endswith(".rels"):
                    text = archive.read(name).decode()
                    # Every internal relationship points at a part that exists.
                    base = str(Path(name).parent.parent)
                    for target in __import__("re").findall(r'Target="([^"]+)"(?![^>]*External)', text):
                        resolved = Path("/" + base, target).resolve() if not target.startswith("/") else Path(target)
                        self.assertIn(str(resolved).lstrip("/"), names, (name, target))
            self.assertFalse(any("TEMPLATE SAMPLE" in archive.read(n).decode(errors="ignore")
                                 for n in names if n.startswith("ppt/slides/slide")))

    def test_check_reports_leftovers_overflow_and_off_profile_fonts(self):
        deck = next(iter(self.ingest()["decks"]))
        plan = {"slides": [{"from": f"{deck}:2", "fill": {"ph:0": "TODO", "ph:1": ["長い文章" * 120]}},
                           {"layout": "Title and Content", "fill": {"ph:0": "空の本文"}}]}
        (self.root / "bad.json").write_text(json.dumps(plan, ensure_ascii=False))
        out = self.root / "bad.pptx"
        self.slides("build", "--library", self.library, "--plan", self.root / "bad.json", "--out", out, "--no-render")
        result = self.slides("check", out, "--library", self.library, "--json", check=False)
        self.assertEqual(result.returncode, 1)
        messages = [i["message"] for i in json.loads(result.stdout)["issues"]]
        self.assertTrue(any("placeholder text" in m for m in messages), messages)
        self.assertTrue(any("likely overflows" in m for m in messages), messages)
        self.assertTrue(any("empty placeholder" in m for m in messages), messages)
        self.assertTrue(any("denser than" in m for m in messages), messages)

    def test_fonts_survive_other_themes_mixed_runs_and_embedding(self):
        deck = next(iter(self.ingest()["decks"]))
        library = self.root / "library-two"
        self.slides("ingest", "--library", library, "--template", self.root / "template.pptx",
                    self.root / "decks", self.root / "other.pptx", "--no-render")
        other = next(d for d in json.loads((library / "library.json").read_text())["decks"] if d.startswith("other"))
        model = json.loads((library / "model" / f"{other}.json").read_text())
        box = model["slides"][0]["shapes"][-1]
        self.assertEqual(box["text"]["paragraphs"][0]["runs"][0]["latin"], "Georgia")
        self.assertEqual(model["embedded_fonts"], [{"typeface": "Georgia"}])
        plan = {"slides": [
            {"from": f"{other}:1"},
            {"from": f"{deck}:2", "fill": {"ph:1": [
                {"runs": [{"text": "計算量は "}, {"text": "O(n)", "style": 1}]},
                {"runs": [{"text": "前の段落の書式", "style": [0, 1], "bold": True}], "level": 1}]}}]}
        (self.root / "fonts.json").write_text(json.dumps(plan, ensure_ascii=False))
        out = self.root / "fonts" / "deck.pptx"
        result = self.slides("build", "--library", library, "--plan", self.root / "fonts.json",
                             "--out", out, "--no-render")
        self.assertIn("theme or master differs from the template", result.stdout)
        report = (self.root / "fonts" / "deck-report.md").read_text()
        self.assertIn("theme or master differs", report)
        self.assertIn("embedded font 'Georgia'", report)
        check = subprocess.run([*UV, "-c", "import sys, json; sys.path.insert(0, sys.argv[2]); import ooxml; "
                                "print(json.dumps(ooxml.extract(sys.argv[1]), ensure_ascii=False))",
                                str(out), str(SLIDES.parent)], capture_output=True, text=True, check=True, timeout=300)
        built = json.loads(check.stdout)
        texts = {p["text"]: p["runs"] for s in built["slides"] for shape in s["shapes"]
                 for p in (shape.get("text") or {}).get("paragraphs", [])}
        self.assertEqual(texts["テーマのフォントを受け継ぐ文"][0]["latin"], "Georgia")  # pinned against the Calibri template
        self.assertEqual([r.get("latin") for r in texts["計算量は O(n)"]], ["Calibri", "Consolas"])
        self.assertEqual((texts["前の段落の書式"][0].get("latin"), texts["前の段落の書式"][0].get("bold")),
                         ("Consolas", True))
        self.assertEqual(built["embedded_fonts"], [{"typeface": "Georgia"}])
        with zipfile.ZipFile(out) as archive:
            fonts = [n for n in archive.namelist() if n.endswith(".fntdata")]
            self.assertEqual([archive.read(n) for n in fonts], [b"FAKEFONTDATA"])

    def test_plan_errors_name_the_slide(self):
        self.ingest()
        (self.root / "wrong.json").write_text(json.dumps({"slides": [{"layout": "Nope"}]}))
        result = self.slides("build", "--library", self.library, "--plan", self.root / "wrong.json",
                             "--out", self.root / "wrong.pptx", "--no-render", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no layout named 'Nope'", result.stderr)


if __name__ == "__main__":
    unittest.main()
