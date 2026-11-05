"""Read a .pptx package completely from its XML, without python-pptx.

`extract(path)` returns a JSON-ready model of the presentation: every slide's shapes with
absolute geometry, effective (inherited) text, paragraph and shape formatting, equations,
tables, charts, SmartArt, media, backgrounds, transitions, animations and notes, together
with the masters, layouts and theme those slides use. Any element the interpreter does not
understand is kept as an XML excerpt under `uninterpreted`, so nothing is silently dropped;
`raw_parts` gives the untouched XML of any part.
"""

import colorsys
import io
import posixpath
import re
import zipfile

from lxml import etree

MODEL_VERSION = 5
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "dsp": "http://schemas.microsoft.com/office/drawing/2008/diagram",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "a14": "http://schemas.microsoft.com/office/drawing/2010/main",
    "a16": "http://schemas.microsoft.com/office/drawing/2014/main",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
    "p15": "http://schemas.microsoft.com/office/powerpoint/2012/main",
    "p188": "http://schemas.microsoft.com/office/powerpoint/2018/8/main",
    "cx": "http://schemas.microsoft.com/office/drawing/2014/chartex",
    "asvg": "http://schemas.microsoft.com/office/drawing/2016/SVG/main",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
}
PREFIX = {uri: prefix for prefix, uri in NS.items()}
EMU_PER_PT = 12700
SHAPES = {"sp", "pic", "grpSp", "graphicFrame", "cxnSp", "contentPart"}
# Namespaces whose elements carry only editing metadata (IDs, revision marks).
METADATA = {NS["a16"], "http://schemas.microsoft.com/office/drawing/2017/decorative",
            "http://schemas.microsoft.com/office/powerpoint/2015/main",
            "http://schemas.microsoft.com/office/drawing/2018/hyperlinkcolor"}
ANIMATION_NAMES = {("entr", 1): "Appear", ("entr", 2): "Fly In", ("entr", 10): "Fade", ("entr", 22): "Wipe",
                   ("exit", 1): "Disappear", ("exit", 10): "Fade"}


def q(name):
    prefix, local = name.split(":")
    return f"{{{NS[prefix]}}}{local}"


def local(element):
    return etree.QName(element).localname if isinstance(element.tag, str) else None


def tag_name(element):
    name = etree.QName(element)
    return f"{PREFIX.get(name.namespace, name.namespace)}:{name.localname}"


def child(element, *names):
    for name in names:
        if element is None:
            return None
        element = element.find(q(name))
    return element


def children(element, name):
    return [] if element is None else element.findall(q(name))


def emu_pt(value):
    return round(int(value) / EMU_PER_PT, 2) if value not in (None, "") else None


def boolean(value):
    return None if value is None else value in ("1", "true", "on")


# ---------------------------------------------------------------- package


class Package:
    def __init__(self, path):
        self.zip = zipfile.ZipFile(path)
        self.names = set(self.zip.namelist())
        self.cache = {}

    def xml(self, name):
        if name not in self.cache:
            self.cache[name] = etree.fromstring(self.zip.read(name)) if name in self.names else None
        return self.cache[name]

    def blob(self, name):
        return self.zip.read(name) if name in self.names else None

    def rels(self, name):
        directory, base = posixpath.split(name)
        rels_name = posixpath.join(directory, "_rels", base + ".rels")
        root = self.xml(rels_name)
        result = {}
        for rel in children(root, "pr:Relationship"):
            external = rel.get("TargetMode") == "External"
            target = rel.get("Target")
            if not external:
                target = posixpath.normpath(target.lstrip("/") if target.startswith("/")
                                            else posixpath.join(directory, target))
            result[rel.get("Id")] = {"type": rel.get("Type").rsplit("/", 1)[-1], "target": target,
                                     "external": external}
        return result

    def related(self, name, kind):
        return [rel["target"] for rel in self.rels(name).values() if rel["type"] == kind and not rel["external"]]


# ---------------------------------------------------------------- colors


def hex_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_hex(rgb):
    return "#" + "".join(f"{round(max(0, min(1, c)) * 255):02X}" for c in rgb)


PRESET_COLORS = {"black": "000000", "white": "FFFFFF", "red": "FF0000", "green": "008000", "blue": "0000FF",
                 "yellow": "FFFF00", "gray": "808080", "orange": "FFA500", "darkBlue": "00008B",
                 "darkRed": "8B0000", "lightGray": "D3D3D3", "darkGray": "A9A9A9"}


class Theme:
    def __init__(self, root):
        self.colors, self.fonts, self.name = {}, {}, None
        if root is None:
            return
        self.name = root.get("name")
        scheme = root.find(".//" + q("a:clrScheme"))
        for element in scheme if scheme is not None else []:
            if not isinstance(element.tag, str):
                continue
            value = child(element, "a:srgbClr")
            system = child(element, "a:sysClr")
            self.colors[local(element)] = ("#" + value.get("val").upper() if value is not None
                                           else "#" + system.get("lastClr", "000000").upper() if system is not None
                                           else None)
        for kind, key in (("majorFont", "major"), ("minorFont", "minor")):
            font = root.find(".//" + q("a:fontScheme") + "/" + q("a:" + kind))
            if font is None:
                continue
            entry = {script: child(font, "a:" + script).get("typeface") if child(font, "a:" + script) is not None
                     else None for script in ("latin", "ea", "cs")}
            entry["scripts"] = {f.get("script"): f.get("typeface") for f in children(font, "a:font")}
            self.fonts[key] = entry
        fmt = root.find(".//" + q("a:fmtScheme"))
        self.format = {local(lst): len([e for e in lst if isinstance(e.tag, str)])
                       for lst in (fmt if fmt is not None else []) if isinstance(lst.tag, str)}

    def typeface(self, face):
        # +mj-lt / +mn-ea style references name the theme's major/minor fonts.
        match = re.fullmatch(r"\+(mj|mn)-(lt|ea|cs)", face or "")
        if not match:
            return face
        fonts = self.fonts.get("major" if match.group(1) == "mj" else "minor", {})
        script = {"lt": "latin", "ea": "ea", "cs": "cs"}[match.group(2)]
        return fonts.get(script) or (fonts.get("scripts", {}).get("Jpan") if script == "ea" else None) or None


class Colors:
    """Resolve DrawingML colors to RGB through the color map and theme."""

    def __init__(self, theme, color_map):
        self.theme, self.map = theme, color_map

    def scheme(self, name, placeholder=None):
        if name == "phClr" and placeholder:
            return placeholder.get("rgb")
        name = self.map.get(name, name)
        return self.theme.colors.get(name)

    def resolve(self, element, placeholder=None):
        """`element` is a color element or a fill containing one; returns {rgb, scheme, alpha} or None."""
        if element is None:
            return None
        kinds = ("srgbClr", "schemeClr", "sysClr", "prstClr", "scrgbClr", "hslClr")
        if local(element) not in kinds:
            element = next((e for e in element if local(e) in kinds), None)
            if element is None:
                return None
        kind, value, scheme = local(element), None, None
        if kind == "srgbClr":
            value = "#" + element.get("val").upper()
        elif kind == "schemeClr":
            scheme = element.get("val")
            value = self.scheme(scheme, placeholder)
        elif kind == "sysClr":
            value = "#" + element.get("lastClr", "000000").upper()
        elif kind == "prstClr":
            value = "#" + PRESET_COLORS.get(element.get("val"), "000000")
        elif kind == "scrgbClr":
            value = rgb_hex([int(element.get(k)) / 100000 for k in ("r", "g", "b")])
        elif kind == "hslClr":
            hue = int(element.get("hue")) / 21600000
            value = rgb_hex(colorsys.hls_to_rgb(hue, int(element.get("lum")) / 100000,
                                                int(element.get("sat")) / 100000))
        result = {"rgb": value}
        if scheme:
            result["scheme"] = scheme
        if value:
            rgb, alpha = list(hex_rgb(value)), None
            for mod in element:
                name, amount = local(mod), int(mod.get("val", "0")) / 100000
                if name in ("lumMod", "lumOff", "satMod"):
                    h, l, s = colorsys.rgb_to_hls(*rgb)
                    if name == "lumMod":
                        l *= amount
                    elif name == "lumOff":
                        l += amount
                    else:
                        s *= amount
                    rgb = list(colorsys.hls_to_rgb(h, max(0, min(1, l)), max(0, min(1, s))))
                elif name == "tint":
                    rgb = [c + (1 - c) * (1 - amount) for c in rgb]
                elif name == "shade":
                    rgb = [c * amount for c in rgb]
                elif name == "alpha":
                    alpha = round(amount, 3)
            result["rgb"] = rgb_hex(rgb)
            if alpha is not None and alpha < 1:
                result["alpha"] = alpha
        return result


def color_map(element):
    return {} if element is None else dict(element.attrib)


# ---------------------------------------------------------------- property inheritance

GROUPS = {
    "noFill": "fill", "solidFill": "fill", "gradFill": "fill", "blipFill": "fill", "pattFill": "fill", "grpFill": "fill",
    "buNone": "bullet", "buAutoNum": "bullet", "buChar": "bullet", "buBlip": "bullet",
    "buClrTx": "buClr", "buClr": "buClr", "buSzTx": "buSz", "buSzPct": "buSz", "buSzPts": "buSz",
    "buFontTx": "buFont", "buFont": "buFont",
    "normAutofit": "autofit", "spAutoFit": "autofit", "noAutofit": "autofit",
}


class Props:
    """Attributes and child elements of a pPr/rPr/bodyPr, merged from general to specific."""

    def __init__(self):
        self.attrs, self.items = {}, {}

    def merge(self, element):
        if element is None:
            return self
        self.attrs.update(element.attrib)
        for item in element:
            if isinstance(item.tag, str):
                self.items[GROUPS.get(local(item), local(item))] = item
        return self

    def copy(self):
        clone = Props()
        clone.attrs, clone.items = dict(self.attrs), dict(self.items)
        return clone


def level_style(list_style, level):
    return None if list_style is None else child(list_style, f"a:lvl{level + 1}pPr")


class TextContext:
    """The list-style chain a shape's text inherits from (most general first)."""

    def __init__(self, styles, body_props, font_ref=None):
        self.styles = styles  # list of lstStyle-like elements (each with lvlNpPr)
        self.body_props = body_props  # list of bodyPr elements
        self.font_ref = font_ref  # p:style/a:fontRef

    def paragraph(self, level):
        props = Props()
        for style in self.styles:
            props.merge(level_style(style, level))
        return props

    def run(self, level):
        props = Props()
        if self.font_ref is not None:
            idx = self.font_ref.get("idx")
            props.attrs["_fontRef"] = idx
            fill = next((e for e in self.font_ref if isinstance(e.tag, str)), None)
            if fill is not None:
                props.items["fill"] = fill
        for style in self.styles:
            props.merge(child(level_style(style, level), "a:defRPr"))
        return props

    def body(self):
        props = Props()
        for body in self.body_props:
            props.merge(body)
        return props


# ---------------------------------------------------------------- equations


def omml(element):
    """Linearize an OMML equation into LaTeX-like text."""
    if element is None:
        return ""
    name = local(element)
    get = lambda n: omml(element.find(q("m:" + n)))  # noqa: E731
    if name == "t":
        return element.text or ""
    if name in ("rPr", "ctrlPr") or name.endswith("Pr"):
        return ""
    if name == "f":
        return "\\frac{" + get("num") + "}{" + get("den") + "}"
    if name == "sSup":
        return get("e") + "^{" + get("sup") + "}"
    if name == "sSub":
        return get("e") + "_{" + get("sub") + "}"
    if name == "sSubSup":
        return get("e") + "_{" + get("sub") + "}^{" + get("sup") + "}"
    if name == "sPre":
        return "{}_{" + get("sub") + "}^{" + get("sup") + "}" + get("e")
    if name == "rad":
        hidden = child(element, "m:radPr", "m:degHide")
        degree = "" if hidden is not None and hidden.get(q("m:val"), "1") in ("1", "on") else get("deg")
        return "\\sqrt" + (f"[{degree}]" if degree else "") + "{" + get("e") + "}"
    if name == "nary":
        symbol = child(element, "m:naryPr", "m:chr")
        operator = symbol.get(q("m:val")) if symbol is not None else "∫"
        return operator + "_{" + get("sub") + "}^{" + get("sup") + "}{" + get("e") + "}"
    if name == "d":
        props = child(element, "m:dPr")
        begin = child(props, "m:begChr")
        end = child(props, "m:endChr")
        separator = child(props, "m:sepChr")
        parts = [omml(e) for e in children(element, "m:e")]
        return ((begin.get(q("m:val")) if begin is not None else "(")
                + (separator.get(q("m:val")) if separator is not None else ",").join(parts)
                + (end.get(q("m:val")) if end is not None else ")"))
    if name == "acc":
        mark = child(element, "m:accPr", "m:chr")
        return "\\accent{" + (mark.get(q("m:val")) if mark is not None else "^") + "}{" + get("e") + "}"
    if name == "bar":
        return "\\overline{" + get("e") + "}"
    if name == "func":
        return get("fName") + "(" + get("e") + ")"
    if name == "limLow":
        return get("e") + "_{" + get("lim") + "}"
    if name == "limUpp":
        return get("e") + "^{" + get("lim") + "}"
    if name == "m":
        rows = [" & ".join(omml(e) for e in children(row, "m:e")) for row in children(element, "m:mr")]
        return "\\begin{matrix}" + " \\\\ ".join(rows) + "\\end{matrix}"
    if name == "eqArr":
        return " \\\\ ".join(omml(e) for e in children(element, "m:e"))
    if name == "groupChr":
        mark = child(element, "m:groupChrPr", "m:chr")
        return "\\group{" + (mark.get(q("m:val")) if mark is not None else "⏟") + "}{" + get("e") + "}"
    if name == "oMathPara":
        return "\n".join(omml(e) for e in children(element, "m:oMath"))
    return "".join(omml(e) for e in element if isinstance(e.tag, str))


# ---------------------------------------------------------------- reader


class Reader:
    def __init__(self, path, image_size=None):
        self.package = Package(path)
        self.image_size = image_size
        presentation = "ppt/presentation.xml"
        self.presentation_name = presentation
        self.presentation = self.package.xml(presentation)
        if self.presentation is None:
            raise ValueError("not a PowerPoint package (ppt/presentation.xml is missing)")
        self.default_style = child(self.presentation, "p:defaultTextStyle")
        self.uninterpreted = []
        self.handled_parts = set()

    # -- generic helpers

    def leftovers(self, root, part, handled, limit=60):
        """Record top-most elements under `root` that the interpreter does not read."""
        found = []

        def visit(element, path):
            for item in element:
                if not isinstance(item.tag, str):
                    continue
                name = etree.QName(item)
                if name.namespace in METADATA or name.localname in ("extLst", "ext") and self.metadata_ext(item):
                    continue
                key = tag_name(item)
                where = path + "/" + key
                if key not in handled and name.namespace != NS["m"]:
                    shape = self.owner_id(item)
                    text = etree.tostring(item, encoding="unicode")
                    found.append({"part": part, "path": where, "shape_id": shape,
                                  "xml": text if len(text) <= 1500 else text[:1500] + "…"})
                    continue
                visit(item, where)

        visit(root, tag_name(root))
        extra = len(found) - limit
        result = found[:limit]
        if extra > 0:
            result.append({"part": part, "path": None, "xml": f"... {extra} more; use `raw` on this part"})
        return result

    def metadata_ext(self, element):
        uri = element.get("uri", "")
        # creationId/modId and similar bookkeeping extensions say nothing about appearance.
        return local(element) == "ext" and uri in (
            "{FF2B5EF4-FFF2-40B4-BE49-F238E27FC236}", "{BB962C8B-B14F-4D97-AF65-F5344CB8AC3E}",
            "{C183D7F6-B498-43B3-948B-1728B52AA6E4}", "{3A86A75C-4F4B-4683-9AE1-C65F6400EC91}")

    def owner_id(self, element):
        while element is not None:
            if local(element) in SHAPES:
                props = element.find(".//" + q("p:cNvPr"))
                return int(props.get("id")) if props is not None and props.get("id", "").isdigit() else None
            element = element.getparent()
        return None

    # -- masters, layouts, themes

    def layout_context(self, layout_name):
        if layout_name in self.handled_parts:
            return self.contexts[layout_name]
        if not hasattr(self, "contexts"):
            self.contexts = {}
        layout = self.package.xml(layout_name)
        master_name = (self.package.related(layout_name, "slideMaster") or [None])[0]
        master = self.package.xml(master_name) if master_name else None
        theme_name = (self.package.related(master_name, "theme") or [None])[0] if master_name else None
        theme = Theme(self.package.xml(theme_name) if theme_name else None)
        context = {"layout": layout, "layout_name": layout_name, "master": master, "master_name": master_name,
                   "theme": theme, "theme_name": theme_name,
                   "color_map": color_map(child(master, "p:clrMap"))}
        self.contexts[layout_name] = context
        self.handled_parts.add(layout_name)
        return context

    @staticmethod
    def placeholder(shape):
        ph = shape.find(".//" + q("p:nvPr") + "/" + q("p:ph")) if shape is not None else None
        if ph is None:
            return None
        return {"type": ph.get("type", "obj"), "idx": int(ph.get("idx", "0")),
                "size": ph.get("sz"), "orient": ph.get("orient"), "has_custom_prompt": boolean(ph.get("hasCustomPrompt"))}

    @staticmethod
    def find_placeholder(tree, ph, by_index=True):
        if tree is None or ph is None:
            return None
        title = ph["type"] in ("title", "ctrTitle")
        candidates = [s for s in tree.iter(q("p:sp"), q("p:pic"), q("p:graphicFrame"))
                      if Reader.placeholder(s) is not None]
        if by_index:
            for shape in candidates:
                other = Reader.placeholder(shape)
                if other["idx"] == ph["idx"] and (ph["idx"] != 0 or not title or other["type"] in ("title", "ctrTitle")):
                    return shape
        kind = {"ctrTitle": "title", "subTitle": "body", "obj": "body"}.get(ph["type"], ph["type"])
        for shape in candidates:
            other = Reader.placeholder(shape)["type"]
            if {"ctrTitle": "title", "subTitle": "body", "obj": "body"}.get(other, other) == kind:
                return shape
        return None

    def text_context(self, shape, ph, context, table=False):
        master = context["master"]
        styles, bodies, font_ref = [], [], None
        if table:
            styles.append(self.default_style)
        elif ph is not None:
            styles.append(self.default_style)
            styles_root = child(master, "p:txStyles")
            styles.append(child(styles_root, "p:titleStyle") if ph["type"] in ("title", "ctrTitle")
                          else child(styles_root, "p:otherStyle") if ph["type"] in ("dt", "ftr", "sldNum")
                          else child(styles_root, "p:bodyStyle"))
            for tree, by_index in ((master, False), (context["layout"], True)):
                inherited = self.find_placeholder(tree, ph, by_index)
                if inherited is not None:
                    body = child(inherited, "p:txBody")
                    styles.append(child(body, "a:lstStyle"))
                    bodies.append(child(body, "a:bodyPr"))
        else:
            styles.append(self.default_style)
            font_ref = child(shape, "p:style", "a:fontRef")
        body = child(shape, "p:txBody") if not table else shape
        styles.append(child(body, "a:lstStyle"))
        bodies.append(child(body, "a:bodyPr"))
        return TextContext([s for s in styles if s is not None], [b for b in bodies if b is not None], font_ref)

    # -- formatting

    def fill(self, props_parent, colors, style_ref=None):
        if props_parent is None:
            return None
        for item in props_parent:
            kind = local(item)
            if kind == "noFill":
                return {"type": "none"}
            if kind == "solidFill":
                return {"type": "solid", "color": colors.resolve(item)}
            if kind == "gradFill":
                stops = [{"pos": int(stop.get("pos")) / 1000, "color": colors.resolve(stop)}
                         for stop in children(child(item, "a:gsLst"), "a:gs")]
                linear = child(item, "a:lin")
                return {"type": "gradient", "stops": stops,
                        "angle": int(linear.get("ang", "0")) / 60000 if linear is not None else None,
                        "path": child(item, "a:path").get("path") if child(item, "a:path") is not None else None}
            if kind == "pattFill":
                return {"type": "pattern", "preset": item.get("prst"),
                        "foreground": colors.resolve(child(item, "a:fgClr")),
                        "background": colors.resolve(child(item, "a:bgClr"))}
            if kind == "blipFill":
                return {"type": "picture"}
            if kind == "grpFill":
                return {"type": "group"}
        if style_ref is not None and style_ref.get("idx") not in (None, "0"):
            return {"type": "theme-style", "index": int(style_ref.get("idx")), "color": colors.resolve(style_ref)}
        return None

    def line(self, line, colors, style_ref=None):
        if line is None:
            if style_ref is not None and style_ref.get("idx") not in (None, "0"):
                return {"theme_style": int(style_ref.get("idx")), "color": colors.resolve(style_ref)}
            return None
        result = {"width_pt": emu_pt(line.get("w")), "cap": line.get("cap"), "compound": line.get("cmpd")}
        fill = self.fill(line, colors)
        if fill and fill["type"] == "none":
            return {"none": True}
        if fill:
            result["color"] = fill.get("color") or fill
        elif style_ref is not None:
            result["color"] = colors.resolve(style_ref)
        dash = child(line, "a:prstDash")
        if dash is not None:
            result["dash"] = dash.get("val")
        if child(line, "a:custDash") is not None:
            result["dash"] = "custom"
        for end in ("headEnd", "tailEnd"):
            arrow = child(line, "a:" + end)
            if arrow is not None and arrow.get("type", "none") != "none":
                result[end] = {"type": arrow.get("type"), "w": arrow.get("w"), "len": arrow.get("len")}
        for join in ("round", "bevel", "miter"):
            if child(line, "a:" + join) is not None:
                result["join"] = join
        return {k: v for k, v in result.items() if v is not None}

    def effects(self, props, colors, style_ref=None):
        effects = child(props, "a:effectLst")
        result = []
        for effect in effects if effects is not None else []:
            if not isinstance(effect.tag, str):
                continue
            item = {"type": local(effect)}
            for key in ("blurRad", "dist", "rad", "size"):
                if effect.get(key):
                    item[key + "_pt"] = emu_pt(effect.get(key))
            if effect.get("dir"):
                item["direction"] = int(effect.get("dir")) / 60000
            color = colors.resolve(effect)
            if color:
                item["color"] = color
            result.append(item)
        if child(props, "a:scene3d") is not None or child(props, "a:sp3d") is not None:
            result.append({"type": "3d"})
        if not result and style_ref is not None and style_ref.get("idx") not in (None, "0"):
            result.append({"type": "theme-effect", "index": int(style_ref.get("idx"))})
        return result

    def run_format(self, props, colors, theme):
        attrs, items = props.attrs, props.items
        result = {
            "size": int(attrs["sz"]) / 100 if attrs.get("sz") else None,
            "bold": boolean(attrs.get("b")), "italic": boolean(attrs.get("i")),
            "underline": None if attrs.get("u") in (None, "none") else attrs.get("u"),
            "strike": None if attrs.get("strike") in (None, "noStrike") else attrs.get("strike"),
            "baseline": int(attrs["baseline"]) / 1000 if attrs.get("baseline") else None,
            "spacing_pt": int(attrs["spc"]) / 100 if attrs.get("spc") else None,
            "caps": attrs.get("cap") if attrs.get("cap") not in (None, "none") else None,
            "lang": attrs.get("lang") or attrs.get("altLang"),
        }
        for script in ("latin", "ea", "cs", "sym"):
            if script in items:
                result[script] = theme.typeface(items[script].get("typeface"))
        if "_fontRef" in attrs and not result.get("latin"):
            kind = {"major": "major", "minor": "minor"}.get(attrs["_fontRef"])
            if kind:
                fonts = theme.fonts.get(kind, {})
                result.setdefault("latin", fonts.get("latin"))
                result.setdefault("ea", fonts.get("ea") or fonts.get("scripts", {}).get("Jpan"))
        fill = items.get("fill")
        if fill is not None:
            kind = local(fill)
            if kind in ("solidFill",) or kind in ("srgbClr", "schemeClr", "sysClr", "prstClr", "scrgbClr", "hslClr"):
                result["color"] = colors.resolve(fill)
            elif kind == "gradFill":
                result["color"] = {"gradient": True, **(colors.resolve(child(child(fill, "a:gsLst"), "a:gs")) or {})}
            elif kind == "noFill":
                result["color"] = {"none": True}
        if "highlight" in items:
            result["highlight"] = colors.resolve(items["highlight"])
        if "ln" in items:
            result["outline"] = self.line(items["ln"], colors)
        if "effectLst" in items:
            result["effects"] = [local(e) for e in items["effectLst"] if isinstance(e.tag, str)]
        for kind in ("hlinkClick", "hlinkMouseOver"):
            if kind in items:
                result["link"] = {"rId": items[kind].get(q("r:id")), "action": items[kind].get("action")}
        return {k: v for k, v in result.items() if v not in (None, False, [], {})}

    def paragraph_format(self, props, colors, theme):
        attrs, items = props.attrs, props.items
        result = {"align": attrs.get("algn", "l"), "margin_left_pt": emu_pt(attrs.get("marL")),
                  "indent_pt": emu_pt(attrs.get("indent")), "rtl": boolean(attrs.get("rtl"))}
        for name in ("lnSpc", "spcBef", "spcAft"):
            if name in items:
                percent = child(items[name], "a:spcPct")
                points = child(items[name], "a:spcPts")
                result[name] = (f"{int(percent.get('val')) / 1000:g}%" if percent is not None
                                else f"{int(points.get('val')) / 100:g}pt" if points is not None else None)
        bullet = items.get("bullet")
        if bullet is not None:
            kind = local(bullet)
            result["bullet"] = ({"type": "none"} if kind == "buNone"
                                else {"type": "char", "char": bullet.get("char")} if kind == "buChar"
                                else {"type": "number", "scheme": bullet.get("type"), "start": bullet.get("startAt")}
                                if kind == "buAutoNum" else {"type": "picture"})
            if "buFont" in items and local(items["buFont"]) == "buFont":
                result["bullet"]["font"] = theme.typeface(items["buFont"].get("typeface"))
            if "buClr" in items and local(items["buClr"]) == "buClr":
                result["bullet"]["color"] = colors.resolve(items["buClr"])
            if "buSz" in items and local(items["buSz"]) != "buSzTx":
                size = items["buSz"]
                result["bullet"]["size"] = (f"{int(size.get('val')) / 1000:g}%" if local(size) == "buSzPct"
                                            else f"{int(size.get('val')) / 100:g}pt")
        if "tabLst" in items:
            result["tabs_pt"] = [emu_pt(tab.get("pos")) for tab in children(items["tabLst"], "a:tab")]
        return {k: v for k, v in result.items() if v not in (None, False)}

    def body_format(self, props):
        attrs, items = props.attrs, props.items
        result = {"anchor": attrs.get("anchor", "t"), "anchor_center": boolean(attrs.get("anchorCtr")),
                  "wrap": attrs.get("wrap", "square"), "vertical": attrs.get("vert") if attrs.get("vert") != "horz" else None,
                  "columns": int(attrs["numCol"]) if attrs.get("numCol") else None,
                  "rotation": int(attrs["rot"]) / 60000 if attrs.get("rot") else None,
                  "insets_pt": [emu_pt(attrs.get(k, d)) for k, d in
                                (("lIns", 91440), ("tIns", 45720), ("rIns", 91440), ("bIns", 45720))]}
        autofit = items.get("autofit")
        if autofit is not None:
            result["autofit"] = local(autofit)
            if autofit.get("fontScale"):
                result["font_scale"] = int(autofit.get("fontScale")) / 1000
            if autofit.get("lnSpcReduction"):
                result["line_reduction"] = int(autofit.get("lnSpcReduction")) / 1000
        if "prstTxWarp" in items:
            result["warp"] = items["prstTxWarp"].get("prst")
        return {k: v for k, v in result.items() if v not in (None, False)}

    def text(self, body, context, text_context, colors, rels):
        theme = context["theme"]
        paragraphs = []
        for paragraph in children(body, "a:p"):
            ppr = child(paragraph, "a:pPr")
            level = int(ppr.get("lvl", "0")) if ppr is not None else 0
            pprops = text_context.paragraph(level).merge(ppr)
            base = text_context.run(level)
            runs = []
            for item in paragraph:
                kind = local(item)
                if kind in ("r", "fld"):
                    props = base.copy().merge(child(item, "a:rPr"))
                    run = {"text": child(item, "a:t").text or "" if child(item, "a:t") is not None else ""}
                    if kind == "fld":
                        run["field"] = item.get("type")
                    run.update(self.run_format(props, colors, theme))
                    if "link" in run:
                        target = rels.get(run["link"].pop("rId"), {})
                        run["link"]["target"] = target.get("target")
                    runs.append(run)
                elif kind == "br":
                    runs.append({"text": "\n", "break": True})
                elif kind == "AlternateContent":
                    math = item.find(".//" + q("m:oMathPara"))
                    if math is None:
                        math = item.find(".//" + q("m:oMath"))
                    if math is not None:
                        props = base.copy().merge(item.find(".//" + q("a:rPr")))
                        runs.append({"text": omml(math), "math": True, **self.run_format(props, colors, theme)})
                    else:
                        runs.append({"text": "".join(item.itertext()), "alternate": True})
            text = "".join(r["text"] for r in runs)
            entry = {"text": text, "level": level, "format": self.paragraph_format(pprops, colors, theme),
                     "runs": runs}
            if not runs:
                entry["empty_run_format"] = self.run_format(base.copy().merge(child(paragraph, "a:endParaRPr")),
                                                            colors, theme)
            paragraphs.append(entry)
        return {"body": self.body_format(text_context.body()), "paragraphs": paragraphs}

    # -- shapes

    def transform(self, xfrm, parent):
        if xfrm is None:
            return None
        off, ext = child(xfrm, "a:off"), child(xfrm, "a:ext")
        if off is None or ext is None:
            return None
        x, y, w, h = (int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy")))
        if parent:
            x, y = parent["x"] + (x - parent["cx"]) * parent["sx"], parent["y"] + (y - parent["cy"]) * parent["sy"]
            w, h = w * parent["sx"], h * parent["sy"]
        return {"x": x, "y": y, "w": w, "h": h, "rotation": int(xfrm.get("rot", "0")) / 60000,
                "flip_h": boolean(xfrm.get("flipH")), "flip_v": boolean(xfrm.get("flipV"))}

    def group_transform(self, xfrm, parent):
        box = self.transform(xfrm, parent)
        off, ext = child(xfrm, "a:chOff"), child(xfrm, "a:chExt")
        if box is None or off is None or ext is None:
            return parent
        cw, ch = int(ext.get("cx")) or 1, int(ext.get("cy")) or 1
        return {"x": box["x"], "y": box["y"], "cx": int(off.get("x")), "cy": int(off.get("y")),
                "sx": box["w"] / cw, "sy": box["h"] / ch}

    def box(self, element, xfrm, ph, context, parent):
        box = self.transform(xfrm, parent)
        inherited = False
        if box is None and ph is not None:
            for tree, by_index in ((context["layout"], True), (context["master"], False)):
                source = self.find_placeholder(tree, ph, by_index)
                if source is not None:
                    box = self.transform(source.find(".//" + q("a:xfrm")), None)
                    if box is not None:
                        inherited = True
                        break
        if box is None:
            return None
        result = {"x": emu_pt(box["x"]), "y": emu_pt(box["y"]), "w": emu_pt(box["w"]), "h": emu_pt(box["h"])}
        for key in ("rotation", "flip_h", "flip_v"):
            if box.get(key):
                result[key] = box[key]
        if inherited:
            result["inherited"] = True
        return result

    def shape(self, element, context, colors, rels, parent, part):
        kind = local(element)
        nv = next((e for e in element if isinstance(e.tag, str) and local(e).startswith("nv")), None)
        props = nv.find(q("p:cNvPr")) if nv is not None else None
        ph = self.placeholder(element)
        info = {"id": int(props.get("id")) if props is not None and props.get("id", "").isdigit() else None,
                "name": props.get("name") if props is not None else None,
                "kind": {"sp": "shape", "pic": "picture", "grpSp": "group", "graphicFrame": "frame",
                         "cxnSp": "connector", "contentPart": "ink"}[kind]}
        if props is not None:
            if props.get("descr"):
                info["alt_text"] = props.get("descr")
            if props.get("title"):
                info["alt_title"] = props.get("title")
            if boolean(props.get("hidden")):
                info["hidden"] = True
            for link in ("hlinkClick", "hlinkHover"):
                target = child(props, "a:" + link)
                if target is not None:
                    info["click"] = {"action": target.get("action"),
                                     "target": rels.get(target.get(q("r:id")), {}).get("target")}
        if ph:
            info["placeholder"] = ph
        sppr = child(element, "p:spPr") if kind != "grpSp" else child(element, "p:grpSpPr")
        style = child(element, "p:style")
        xfrm = child(sppr, "a:xfrm") if kind != "graphicFrame" else child(element, "p:xfrm")
        info["box"] = self.box(element, xfrm, ph, context, parent)
        if kind == "grpSp":
            transform = self.group_transform(xfrm, parent)
            info["children"] = self.shapes(element, context, colors, rels, transform, part)
            return info
        if sppr is not None:
            geometry = child(sppr, "a:prstGeom")
            if geometry is not None:
                info["geometry"] = geometry.get("prst")
                adjust = [g.get("fmla") for g in children(child(geometry, "a:avLst"), "a:gd")]
                if adjust:
                    info["adjust"] = adjust
            elif child(sppr, "a:custGeom") is not None:
                info["geometry"] = "custom"
            fill = self.fill(sppr, colors, child(style, "a:fillRef"))
            if fill:
                info["fill"] = fill
            line = self.line(child(sppr, "a:ln"), colors, child(style, "a:lnRef"))
            if line:
                info["line"] = line
            effects = self.effects(sppr, colors, child(style, "a:effectRef"))
            if effects:
                info["effects"] = effects
        if kind == "cxnSp":
            cnv = child(nv, "p:cNvCxnSpPr")
            for end in ("stCxn", "endCxn"):
                link = child(cnv, "a:" + end)
                if link is not None:
                    info[end] = {"shape_id": int(link.get("id")), "site": int(link.get("idx"))}
        if kind == "pic":
            info.update(self.picture(element, rels))
        if kind == "graphicFrame":
            info.update(self.frame(element, context, colors, rels, part))
        if kind == "contentPart":
            info["part"] = rels.get(element.get(q("r:id")), {}).get("target")
        body = child(element, "p:txBody")
        if body is not None and any("".join(p.itertext()).strip() for p in children(body, "a:p")) or (
                body is not None and ph is not None):
            info["text"] = self.text(body, context, self.text_context(element, ph, context), colors, rels)
        media = nv.find(".//" + q("p14:media")) if nv is not None else None
        for kind_name in ("videoFile", "audioFile"):
            item = nv.find(".//" + q("a:" + kind_name)) if nv is not None else None
            if item is not None:
                info["media"] = {"type": kind_name[:-4], "target": rels.get(item.get(q("r:link")), {}).get("target")}
        if media is not None:
            info.setdefault("media", {})["embedded"] = rels.get(media.get(q("r:embed")), {}).get("target")
        return info

    def picture(self, element, rels):
        fill = child(element, "p:blipFill")
        blip = child(fill, "a:blip")
        result = {}
        if blip is not None:
            target = rels.get(blip.get(q("r:embed")) or blip.get(q("r:link")), {})
            name = target.get("target")
            result["image"] = {"part": name, "external": target.get("external", False)}
            if name and not target.get("external"):
                data = self.package.blob(name)
                if data is not None:
                    result["image"]["bytes"] = len(data)
                    result["image"]["ext"] = posixpath.splitext(name)[1].lstrip(".")
                    if self.image_size:
                        size = self.image_size(data)
                        if size:
                            result["image"]["pixels"] = list(size)
            adjustments = [local(e) for e in blip if isinstance(e.tag, str) and local(e) != "extLst"]
            if adjustments:
                result["image"]["adjustments"] = adjustments
            svg = blip.find(".//" + q("asvg:svgBlip"))
            if svg is not None:
                # PowerPoint draws the SVG; the PNG part is only a fallback for older readers.
                result["image"]["svg"] = rels.get(svg.get(q("r:embed")), {}).get("target")
        crop = child(fill, "a:srcRect")
        if crop is not None and crop.attrib:
            result["crop"] = {k: int(v) / 1000 for k, v in crop.attrib.items()}
        if child(fill, "a:tile") is not None:
            result["tiled"] = True
        return result

    def frame(self, element, context, colors, rels, part):
        data = element.find(".//" + q("a:graphicData"))
        uri = data.get("uri", "") if data is not None else ""
        if uri.endswith("/table"):
            return {"kind": "table", "table": self.table(child(data, "a:tbl"), context, colors, rels)}
        if uri.endswith("/chart"):
            target = rels.get(child(data, "c:chart").get(q("r:id")), {}).get("target")
            return {"kind": "chart", "chart": self.chart(target)}
        if uri.endswith("/diagram"):
            ids = child(data, "dgm:relIds")
            parts = {key: rels.get(ids.get(q("r:" + key)), {}).get("target") for key in ("dm", "lo", "qs", "cs")}
            return {"kind": "smartart", "smartart": self.smartart(parts, rels)}
        if uri.endswith("/ole"):
            ole = data.find(".//" + q("p:oleObj"))
            return {"kind": "ole", "ole": {"prog_id": ole.get("progId") if ole is not None else None,
                                           "target": rels.get(ole.get(q("r:id")), {}).get("target")
                                           if ole is not None else None}}
        if "chartex" in uri:
            target = rels.get(data.find(".//" + q("cx:chart")).get(q("r:id")), {}).get("target") \
                if data.find(".//" + q("cx:chart")) is not None else None
            return {"kind": "chart", "chart": {"extended": True, "part": target,
                                               "texts": self.part_texts(target)}}
        return {"kind": "frame", "uri": uri}

    def table(self, table, context, colors, rels):
        props = child(table, "a:tblPr")
        style = child(props, "a:tableStyleId")
        result = {"style_id": style.text if style is not None else None,
                  "options": {k: boolean(v) for k, v in (props.attrib.items() if props is not None else [])},
                  "column_widths_pt": [emu_pt(c.get("w")) for c in children(child(table, "a:tblGrid"), "a:gridCol")],
                  "rows": []}
        text_context = self.text_context(table, None, context, table=True)
        for row in children(table, "a:tr"):
            cells = []
            for cell in children(row, "a:tc"):
                entry = {k: (int(v) if v.isdigit() else boolean(v)) for k, v in cell.attrib.items()
                         if k in ("gridSpan", "rowSpan", "hMerge", "vMerge")}
                body = child(cell, "a:txBody")
                if body is not None:
                    content = self.text(body, context, TextContext(text_context.styles + [child(body, "a:lstStyle")],
                                                                    [child(body, "a:bodyPr")]), colors, rels)
                    entry["text"] = "\n".join(p["text"] for p in content["paragraphs"])
                    entry["paragraphs"] = content["paragraphs"]
                tcpr = child(cell, "a:tcPr")
                if tcpr is not None:
                    fill = self.fill(tcpr, colors)
                    if fill:
                        entry["fill"] = fill
                    borders = {side: self.line(child(tcpr, "a:ln" + side), colors) for side in ("L", "R", "T", "B", "TlToBr", "BlToTr")
                               if child(tcpr, "a:ln" + side) is not None}
                    if borders:
                        entry["borders"] = borders
                    if tcpr.get("anchor"):
                        entry["anchor"] = tcpr.get("anchor")
                cells.append(entry)
            result["rows"].append({"height_pt": emu_pt(row.get("h")), "cells": cells})
        return result

    def part_texts(self, name):
        root = self.package.xml(name) if name else None
        return [t.text for t in root.iter(q("a:t")) if t.text] if root is not None else []

    def chart_text(self, element):
        if element is None:
            return None
        rich = element.find(".//" + q("c:rich"))
        if rich is not None:
            return "".join(t.text or "" for t in rich.iter(q("a:t")))
        cache = element.find(".//" + q("c:strCache"))
        if cache is not None:
            return " ".join(v.text or "" for v in cache.iter(q("c:v")))
        value = element.find(".//" + q("c:v"))
        return value.text if value is not None else None

    @staticmethod
    def cache(element):
        if element is None:
            return None
        cache = element.find(".//" + q("c:numCache"))
        if cache is None:
            cache = element.find(".//" + q("c:strCache"))
        if cache is None:
            cache = element.find(".//" + q("c:strLit"))
        if cache is None:
            cache = element.find(".//" + q("c:numLit"))
        if cache is None:
            return None
        points = {int(pt.get("idx")): child(pt, "c:v").text for pt in children(cache, "c:pt")}
        count = child(cache, "c:ptCount")
        size = int(count.get("val")) if count is not None else (max(points) + 1 if points else 0)
        values = [points.get(i) for i in range(size)]
        code = child(cache, "c:formatCode")
        result = {"values": [float(v) if v is not None and re.fullmatch(r"-?[\d.]+(E[-+]?\d+)?", v, re.I) else v
                             for v in values]}
        if code is not None:
            result["format"] = code.text
        reference = element.find(".//" + q("c:f"))
        if reference is not None:
            result["range"] = reference.text
        return result

    def chart(self, name):
        root = self.package.xml(name) if name else None
        if root is None:
            return {"part": name, "missing": True}
        self.handled_parts.add(name)
        chart = child(root, "c:chart")
        colors = Colors(self.theme_for_chart(), {})
        plot = child(chart, "c:plotArea")
        result = {"part": name, "title": self.chart_text(child(chart, "c:title")),
                  "auto_title_deleted": boolean(child(chart, "c:autoTitleDeleted").get("val"))
                  if child(chart, "c:autoTitleDeleted") is not None else None,
                  "plots": [], "axes": []}
        for plot_element in plot if plot is not None else []:
            kind = local(plot_element)
            if not kind or not kind.endswith("Chart"):
                continue
            entry = {"type": kind[:-5]}
            for option in ("barDir", "grouping", "varyColors", "gapWidth", "overlap", "holeSize", "scatterStyle",
                           "radarStyle", "firstSliceAng"):
                element = child(plot_element, "c:" + option)
                if element is not None:
                    entry[option] = element.get("val")
            labels = child(plot_element, "c:dLbls")
            if labels is not None:
                entry["data_labels"] = {local(e)[4:].lower(): e.get("val") for e in labels
                                        if isinstance(e.tag, str) and local(e).startswith("show")}
            series = []
            for item in children(plot_element, "c:ser"):
                spec = {"name": self.chart_text(child(item, "c:tx"))}
                for key in ("cat", "val", "xVal", "yVal", "bubbleSize"):
                    data = self.cache(child(item, "c:" + key))
                    if data:
                        spec[key] = data
                sppr = child(item, "c:spPr")
                fill = self.fill(sppr, colors)
                if fill:
                    spec["fill"] = fill
                line = self.line(child(sppr, "a:ln"), colors)
                if line:
                    spec["line"] = line
                marker = child(item, "c:marker", "c:symbol")
                if marker is not None:
                    spec["marker"] = marker.get("val")
                if child(item, "c:trendline") is not None:
                    spec["trendline"] = child(item, "c:trendline", "c:trendlineType").get("val") \
                        if child(item, "c:trendline", "c:trendlineType") is not None else True
                if child(item, "c:errBars") is not None:
                    spec["error_bars"] = True
                series.append(spec)
            entry["series"] = series
            result["plots"].append(entry)
        for axis in plot if plot is not None else []:
            kind = local(axis)
            if kind not in ("catAx", "valAx", "dateAx", "serAx"):
                continue
            entry = {"type": kind, "title": self.chart_text(child(axis, "c:title"))}
            for option in ("delete", "axPos", "crosses", "tickLblPos", "majorTickMark"):
                element = child(axis, "c:" + option)
                if element is not None:
                    entry[option] = element.get("val")
            scaling = child(axis, "c:scaling")
            for option in ("min", "max", "orientation", "logBase"):
                element = child(scaling, "c:" + option)
                if element is not None:
                    entry[option] = element.get("val")
            number = child(axis, "c:numFmt")
            if number is not None:
                entry["number_format"] = number.get("formatCode")
            entry["major_gridlines"] = child(axis, "c:majorGridlines") is not None
            entry["minor_gridlines"] = child(axis, "c:minorGridlines") is not None
            size = axis.find(".//" + q("c:txPr") + "//" + q("a:defRPr"))
            if size is not None and size.get("sz"):
                entry["font_size"] = int(size.get("sz")) / 100
            result["axes"].append(entry)
        legend = child(chart, "c:legend")
        if legend is not None:
            position = child(legend, "c:legendPos")
            result["legend"] = position.get("val") if position is not None else "r"
        size = root.find(q("c:txPr") + "//" + q("a:defRPr"))
        if size is not None and size.get("sz"):
            result["font_size"] = int(size.get("sz")) / 100
        style = child(root, "c:style")
        if style is not None:
            result["style"] = style.get("val")
        result["uninterpreted"] = self.leftovers(root, name, CHART_HANDLED, limit=25)
        return result

    def theme_for_chart(self):
        # Charts use the presentation theme; the first master's theme is the usual one.
        master = (self.package.related(self.presentation_name, "slideMaster") or [None])[0]
        theme_name = (self.package.related(master, "theme") or [None])[0] if master else None
        return Theme(self.package.xml(theme_name) if theme_name else None)

    def smartart(self, parts, rels):
        data = self.package.xml(parts.get("dm")) if parts.get("dm") else None
        layout = self.package.xml(parts.get("lo")) if parts.get("lo") else None
        result = {"layout": layout.get("uniqueId") if layout is not None else None,
                  "layout_title": None, "nodes": []}
        title = child(layout, "dgm:title")
        if title is not None:
            result["layout_title"] = title.get("val")
        if data is None:
            return result
        for name in parts.values():
            if name:
                self.handled_parts.add(name)
        points = {}
        for point in data.iter(q("dgm:pt")):
            kind = point.get("type", "node")
            if kind in ("node", "doc"):
                text = "\n".join("".join(t.text or "" for t in p.iter(q("a:t"))) for p in point.iter(q("a:p")))
                points[point.get("modelId")] = {"type": kind, "text": text, "children": []}
        connections = sorted((c for c in data.iter(q("dgm:cxn")) if c.get("type", "parOf") == "parOf"),
                             key=lambda c: int(c.get("srcOrd", "0")))
        targets = set()
        for connection in connections:
            source, target = points.get(connection.get("srcId")), points.get(connection.get("destId"))
            if source is not None and target is not None:
                source["children"].append(target)
                targets.add(connection.get("destId"))

        def tree(node):
            return {"text": node["text"], "children": [tree(c) for c in node["children"]]}

        roots = [p for key, p in points.items() if key not in targets]
        documents = [p for p in roots if p["type"] == "doc"] or roots
        result["nodes"] = [tree(c) for d in documents for c in (d["children"] if d["type"] == "doc" else [d])]
        drawing = next((rel["target"] for rel in self.package.rels(parts["dm"]).values()
                        if rel["type"] == "diagramDrawing"), None) if parts.get("dm") else None
        if drawing:
            self.handled_parts.add(drawing)
            root = self.package.xml(drawing)
            if root is not None:
                result["drawn_shapes"] = len(list(root.iter(q("dsp:sp"))))
        return result

    def shapes(self, tree, context, colors, rels, parent, part):
        result = []
        for element in tree:
            kind = local(element)
            if kind in SHAPES:
                result.append(self.shape(element, context, colors, rels, parent, part))
            elif kind == "AlternateContent":
                # Equations and newer features: prefer the rich choice, keep the fallback for reference.
                choice = child(element, "mc:Choice")
                chosen = choice if choice is not None else child(element, "mc:Fallback")
                for item in chosen if chosen is not None else []:
                    if local(item) in SHAPES:
                        shape = self.shape(item, context, colors, rels, parent, part)
                        shape["alternate_content"] = choice.get("Requires") if choice is not None else "fallback"
                        result.append(shape)
        return result

    # -- slide-level

    def background(self, slide_root, colors):
        background = child(slide_root, "p:cSld", "p:bg")
        if background is None:
            return None
        props = child(background, "p:bgPr")
        if props is not None:
            return self.fill(props, colors) or {"type": "unknown"}
        reference = child(background, "p:bgRef")
        if reference is not None:
            return {"type": "theme-background", "index": int(reference.get("idx")),
                    "color": colors.resolve(reference)}
        return None

    def transition(self, slide_root):
        transition = child(slide_root, "p:transition")
        if transition is None:
            alternate = slide_root.find(q("mc:AlternateContent") + "/" + q("mc:Choice") + "/" + q("p:transition"))
            transition = alternate
        if transition is None:
            return None
        effects = [local(e) for e in transition if isinstance(e.tag, str) and local(e) not in ("sndAc", "extLst")]
        return {"effect": effects[0] if effects else None, "speed": transition.get("spd"),
                "duration_ms": transition.get(q("p14:dur")) or transition.get("dur"),
                "advance_on_click": boolean(transition.get("advClick", "1")),
                "advance_after_ms": transition.get("advTm")}

    def animations(self, slide_root):
        timing = child(slide_root, "p:timing")
        if timing is None:
            return []
        result, click = [], 0
        for node in timing.iter(q("p:cTn")):
            node_type = node.get("nodeType")
            if node_type == "clickEffect":
                click += 1
            preset = node.get("presetClass")
            if not preset:
                continue
            target = node.find(".//" + q("p:spTgt"))
            effect = {"click": click, "trigger": node_type, "class": preset,
                      "preset": int(node.get("presetID", "0")), "subtype": node.get("presetSubtype"),
                      "shape_id": int(target.get("spid")) if target is not None and target.get("spid", "").isdigit()
                      else None}
            name = ANIMATION_NAMES.get((preset, effect["preset"]))
            if name:
                effect["name"] = name
            paragraphs = target.find(".//" + q("p:pRg")) if target is not None else None
            if paragraphs is not None:
                effect["paragraphs"] = [int(paragraphs.get("st")), int(paragraphs.get("end"))]
            result.append(effect)
        build = [{"shape_id": int(b.get("spid")), "build": b.get("build")}
                 for b in timing.iter(q("p:bldP")) if b.get("spid", "").isdigit()]
        return result + ([{"text_builds": build}] if build else [])

    def notes(self, slide_name, context):
        notes_name = (self.package.related(slide_name, "notesSlide") or [None])[0]
        root = self.package.xml(notes_name) if notes_name else None
        if root is None:
            return None
        self.handled_parts.add(notes_name)
        master_name = (self.package.related(notes_name, "notesMaster") or [None])[0]
        notes_context = dict(context, layout=None, master=self.package.xml(master_name) if master_name else None)
        colors = Colors(context["theme"], context["color_map"])
        rels = self.package.rels(notes_name)
        for shape in root.iter(q("p:sp")):
            ph = self.placeholder(shape)
            if ph and ph["type"] == "body":
                body = child(shape, "p:txBody")
                text = self.text(body, notes_context, self.text_context(shape, ph, notes_context), colors, rels)
                return {"text": "\n".join(p["text"] for p in text["paragraphs"]).strip(),
                        "paragraphs": text["paragraphs"]}
        return None

    def comments(self, slide_name):
        result = []
        for rel in self.package.rels(slide_name).values():
            if rel["type"] in ("comments", "comment") or rel["type"].endswith("Comment") or "comment" in rel["type"]:
                root = self.package.xml(rel["target"])
                if root is None:
                    continue
                self.handled_parts.add(rel["target"])
                for comment in root.iter(q("p:cm"), q("p188:cm")):
                    text = "".join(comment.itertext()).strip()
                    if text:
                        result.append(text)
        return result

    def slide(self, name, number, hidden, section):
        root = self.package.xml(name)
        layout_name = (self.package.related(name, "slideLayout") or [None])[0]
        context = self.layout_context(layout_name)
        mapping = dict(context["color_map"])
        override = child(root, "p:clrMapOvr", "a:overrideClrMapping")
        if override is not None:
            mapping = color_map(override)
        colors = Colors(context["theme"], mapping)
        rels = self.package.rels(name)
        tree = child(root, "p:cSld", "p:spTree")
        layout = context["layout"]
        result = {
            "number": number, "part": name, "hidden": hidden, "section": section,
            "name": child(root, "p:cSld").get("name") if child(root, "p:cSld") is not None else None,
            "layout": child(layout, "p:cSld").get("name") if layout is not None else None,
            "layout_part": layout_name, "master_part": context["master_name"],
            "background": self.background(root, colors),
            "shows_master_shapes": boolean(root.get("showMasterSp", "1")),
            "shapes": self.shapes(tree, context, colors, rels, None, name) if tree is not None else [],
            "transition": self.transition(root),
            "animations": self.animations(root),
            "notes": self.notes(name, context),
            "comments": self.comments(name),
        }
        result["uninterpreted"] = self.leftovers(root, name, SLIDE_HANDLED)
        return result

    def layout_model(self, name):
        context = self.layout_context(name)
        layout = context["layout"]
        colors = Colors(context["theme"], context["color_map"])
        rels = self.package.rels(name)
        tree = child(layout, "p:cSld", "p:spTree")
        return {"part": name, "name": child(layout, "p:cSld").get("name"), "type": layout.get("type"),
                "master_part": context["master_name"],
                "background": self.background(layout, colors),
                "shows_master_shapes": boolean(layout.get("showMasterSp", "1")),
                "shapes": self.shapes(tree, context, colors, rels, None, name) if tree is not None else [],
                "uninterpreted": self.leftovers(layout, name, SLIDE_HANDLED)}

    def master_model(self, name, layout_name):
        context = self.layout_context(layout_name)
        master = context["master"]
        colors = Colors(context["theme"], context["color_map"])
        rels = self.package.rels(name)
        master_context = dict(context, layout=None)
        tree = child(master, "p:cSld", "p:spTree")
        styles = {}
        for kind in ("titleStyle", "bodyStyle", "otherStyle"):
            style = child(master, "p:txStyles", "p:" + kind)
            levels = []
            for level in range(3):
                text_context = TextContext([s for s in (self.default_style, style) if s is not None], [])
                levels.append({"paragraph": self.paragraph_format(text_context.paragraph(level), colors,
                                                                  context["theme"]),
                               "run": self.run_format(text_context.run(level), colors, context["theme"])})
            styles[kind] = levels
        return {"part": name, "theme": {"name": context["theme"].name, "colors": context["theme"].colors,
                                        "fonts": context["theme"].fonts,
                                        "format_scheme": getattr(context["theme"], "format", {})},
                "color_map": context["color_map"], "background": self.background(master, colors),
                "text_styles": styles,
                "shapes": self.shapes(tree, master_context, colors, rels, None, name) if tree is not None else [],
                "uninterpreted": self.leftovers(master, name, SLIDE_HANDLED)}

    @staticmethod
    def title(slide, height):
        """The slide's title: its title placeholder, else the largest text near the top.

        Templates often draw the title bar with a body placeholder or a text box, so the
        placeholder type alone misses many titles; `inferred` says which rule applied.
        """
        def walk(shapes):
            for shape in shapes:
                yield shape
                yield from walk(shape.get("children", []))

        texts = [s for s in walk(slide["shapes"]) if s.get("text") and any(
            p["text"].strip() for p in s["text"]["paragraphs"])]
        for shape in texts:
            if (shape.get("placeholder") or {}).get("type") in ("title", "ctrTitle"):
                return {"shape_id": shape["id"], "inferred": False,
                        "text": " ".join(p["text"].strip() for p in shape["text"]["paragraphs"] if p["text"].strip())}
        top = [s for s in texts if s.get("box") and s["box"]["y"] + s["box"]["h"] / 2 < height * 0.2]
        if not top:
            return None
        size = lambda s: max([r.get("size") or 0 for p in s["text"]["paragraphs"] for r in p["runs"]] or [0])  # noqa: E731
        shape = max(top, key=lambda s: (size(s), -s["box"]["y"]))
        return {"shape_id": shape["id"], "inferred": True,
                "text": " ".join(p["text"].strip() for p in shape["text"]["paragraphs"] if p["text"].strip())}

    def sections(self):
        result = {}
        for section in self.presentation.iter(q("p14:section")):
            for slide_id in section.iter(q("p14:sldId")):
                result[slide_id.get("id")] = section.get("name")
        return result

    def extract(self):
        rels = self.package.rels(self.presentation_name)
        size = child(self.presentation, "p:sldSz")
        sections = self.sections()
        slides, layouts = [], {}
        for number, slide_id in enumerate(children(child(self.presentation, "p:sldIdLst"), "p:sldId"), 1):
            name = rels[slide_id.get(q("r:id"))]["target"]
            root = self.package.xml(name)
            slide = self.slide(name, number, root.get("show") == "0", sections.get(slide_id.get("id")))
            slide["title"] = self.title(slide, emu_pt(size.get("cy")) if size is not None else 540)
            slides.append(slide)
            layouts.setdefault(slide["layout_part"], None)
        all_layouts = [rel for master in self.package.related(self.presentation_name, "slideMaster")
                       for rel in self.package.related(master, "slideLayout")]
        used = {name: self.layout_model(name) for name in layouts if name}
        masters = {}
        for name in all_layouts:
            context = self.layout_context(name)
            if context["master_name"] not in masters:
                masters[context["master_name"]] = self.master_model(context["master_name"], name)
        fonts = [{"typeface": child(f, "p:font").get("typeface") if child(f, "p:font") is not None else None}
                 for f in children(child(self.presentation, "p:embeddedFontLst"), "p:embeddedFont")]
        return {
            "model_version": MODEL_VERSION,
            "size": [emu_pt(size.get("cx")), emu_pt(size.get("cy"))] if size is not None else None,
            "slide_size_type": size.get("type") if size is not None else None,
            "sections": sorted(set(sections.values())),
            "embedded_fonts": fonts,
            "layouts_available": [{"part": name, "name": child(self.package.xml(name), "p:cSld").get("name")}
                                  for name in all_layouts],
            "layouts_used": used,
            "masters": masters,
            "slides": slides,
            "parts": sorted(self.package.names),
        }


SLIDE_HANDLED = {
    "p:cSld", "p:spTree", "p:nvGrpSpPr", "p:cNvPr", "p:cNvGrpSpPr", "p:nvPr", "p:grpSpPr", "p:sp", "p:pic",
    "p:grpSp", "p:graphicFrame", "p:cxnSp", "p:contentPart", "p:nvSpPr", "p:cNvSpPr", "p:nvPicPr", "p:cNvPicPr",
    "p:nvGraphicFramePr", "p:cNvGraphicFramePr", "p:nvCxnSpPr", "p:cNvCxnSpPr", "p:spPr", "p:style", "p:txBody",
    "p:blipFill", "p:xfrm", "p:ph", "p:bg", "p:bgPr", "p:bgRef", "p:clrMapOvr", "p:clrMap", "p:transition",
    "p:timing", "p:txStyles", "p:titleStyle", "p:bodyStyle", "p:otherStyle", "p:sldLayoutIdLst", "p:hf",
    "a:xfrm", "a:off", "a:ext", "a:chOff", "a:chExt", "a:prstGeom", "a:avLst", "a:gd", "a:custGeom",
    "a:noFill", "a:solidFill", "a:gradFill", "a:gsLst", "a:gs", "a:lin", "a:path", "a:pattFill", "a:fgClr",
    "a:bgClr", "a:blipFill", "a:grpFill", "a:srgbClr", "a:schemeClr", "a:sysClr", "a:prstClr", "a:scrgbClr",
    "a:hslClr", "a:lumMod", "a:lumOff", "a:tint", "a:shade", "a:alpha", "a:satMod", "a:ln", "a:prstDash",
    "a:custDash", "a:headEnd", "a:tailEnd", "a:round", "a:bevel", "a:miter", "a:effectLst", "a:outerShdw",
    "a:innerShdw", "a:glow", "a:softEdge", "a:reflection", "a:prstShdw", "a:blur", "a:scene3d", "a:sp3d",
    "a:lnRef", "a:fillRef", "a:effectRef", "a:fontRef", "a:bodyPr", "a:lstStyle", "a:p", "a:pPr", "a:r",
    "a:rPr", "a:t", "a:br", "a:fld", "a:endParaRPr", "a:latin", "a:ea", "a:cs", "a:sym", "a:hlinkClick",
    "a:hlinkMouseOver", "a:hlinkHover", "a:highlight", "a:lnSpc", "a:spcBef", "a:spcAft", "a:spcPct",
    "a:spcPts", "a:buNone", "a:buAutoNum", "a:buChar", "a:buBlip", "a:buClrTx", "a:buClr", "a:buSzTx",
    "a:buSzPct", "a:buSzPts", "a:buFontTx", "a:buFont", "a:tabLst", "a:tab", "a:defRPr", "a:normAutofit",
    "a:spAutoFit", "a:noAutofit", "a:prstTxWarp", "a:blip", "a:srcRect", "a:stretch", "a:fillRect", "a:tile",
    "a:graphic", "a:graphicData", "a:tbl", "a:tblPr", "a:tableStyleId", "a:tblGrid", "a:gridCol", "a:tr",
    "a:tc", "a:tcPr", "a:lnL", "a:lnR", "a:lnT", "a:lnB", "a:txBody", "a:videoFile", "a:audioFile",
    "a:stCxn", "a:endCxn", "a:spLocks", "a:picLocks", "a:graphicFrameLocks", "a:grpSpLocks", "a:cxnSpLocks",
    "a:lvl1pPr", "a:lvl2pPr", "a:lvl3pPr", "a:lvl4pPr", "a:lvl5pPr", "a:lvl6pPr", "a:lvl7pPr", "a:lvl8pPr",
    "a:lvl9pPr", "a:defPPr", "a:extLst", "p:extLst", "p:ext", "c:chart", "dgm:relIds", "p:oleObj",
    "mc:AlternateContent", "mc:Choice", "mc:Fallback", "a14:m", "p14:media", "p14:creationId", "p14:modId",
    "a:alphaModFix", "a:grayscl", "a:duotone", "a:biLevel", "a:lum", "a:clrChange", "a:clrFrom", "a:clrTo",
    "a:spcFirstLastPara", "a:cNvPr", "a:lnTlToBr", "a:lnBlToTr", "a:masterClrMapping", "a:overrideClrMapping",
    "a:uLnTx", "a:uFillTx", "asvg:svgBlip", "a14:useLocalDpi", "a14:imgProps", "a14:imgLayer",
    "a14:imgEffect", "p:sldLayoutId",
    # PowerPoint keeps the fill/line a shape had before "no fill/line" was chosen; it is not drawn.
    "a14:hiddenFill", "a14:hiddenLine", "a14:hiddenEffects",
}
# Within timing and transitions the interpreter reads effects, triggers, order and targets.
SLIDE_HANDLED |= {"p:tnLst", "p:par", "p:cTn", "p:childTnLst", "p:seq", "p:prevCondLst", "p:nextCondLst",
                  "p:cond", "p:tgtEl", "p:sldTgt", "p:stCondLst", "p:spTgt", "p:txEl", "p:pRg", "p:bldLst", "p:bldP",
                  "p:set", "p:anim", "p:animEffect", "p:animMotion", "p:animRot", "p:animScale", "p:animClr",
                  "p:cBhvr", "p:attrNameLst", "p:attrName", "p:to", "p:strVal", "p:tavLst", "p:tav", "p:val",
                  "p:fltVal", "p:by", "p:from", "p:rCtr", "p:iterate", "p:tmPct", "p:endCondLst", "p:audio",
                  "p:video", "p:cMediaNode", "p:fade", "p:push", "p:wipe", "p:cut", "p:cover", "p:pull",
                  "p:split", "p:zoom", "p:randomBar", "p:dissolve", "p:blinds", "p:checker", "p:circle",
                  "p:comb", "p:diamond", "p:plus", "p:random", "p:strips", "p:wedge", "p:wheel", "p:newsflash",
                  "p:sndAc", "p:stSnd", "p:snd", "p:endSnd", "p14:vortex", "p14:switch", "p14:flip", "p14:ripple",
                  "p14:honeycomb", "p14:prism", "p14:doors", "p14:window", "p14:ferris", "p14:gallery",
                  "p14:conveyor", "p14:pan", "p14:glitter", "p14:warp", "p14:flythrough", "p14:flash",
                  "p14:shred", "p14:reveal", "p14:wheelReverse", "p15:prstTrans", "p14:sectionLst",
                  "p14:section", "p14:sldIdLst", "p14:sldId", "p:custDataLst", "p:tags"}
CHART_HANDLED = {
    "c:date1904", "c:lang", "c:roundedCorners", "c:style", "c:chart", "c:title", "c:tx", "c:rich", "c:overlay",
    "c:autoTitleDeleted", "c:plotArea", "c:layout", "c:legend", "c:legendPos", "c:plotVisOnly", "c:dispBlanksAs",
    "c:txPr", "c:externalData", "c:autoUpdate", "c:ser", "c:idx", "c:order", "c:cat", "c:val", "c:xVal",
    "c:yVal", "c:bubbleSize", "c:strRef", "c:numRef", "c:f", "c:strCache", "c:numCache", "c:ptCount", "c:pt",
    "c:v", "c:formatCode", "c:strLit", "c:numLit", "c:spPr", "c:marker", "c:symbol", "c:size", "c:trendline",
    "c:trendlineType", "c:errBars", "c:dLbls", "c:showLegendKey", "c:showVal", "c:showCatName",
    "c:showSerName", "c:showPercent", "c:showBubbleSize", "c:barDir", "c:grouping", "c:varyColors",
    "c:gapWidth", "c:overlap", "c:holeSize", "c:scatterStyle", "c:radarStyle", "c:firstSliceAng", "c:axId",
    "c:catAx", "c:valAx", "c:dateAx", "c:serAx", "c:scaling", "c:orientation", "c:min", "c:max", "c:logBase",
    "c:delete", "c:axPos", "c:crosses", "c:crossAx", "c:tickLblPos", "c:majorTickMark", "c:minorTickMark",
    "c:numFmt", "c:majorGridlines", "c:minorGridlines", "c:auto", "c:lblAlgn", "c:lblOffset", "c:noMultiLvlLbl",
    "c:crossBetween", "c:smooth", "c:invertIfNegative", "c:extLst", "c:ext", "c:printSettings",
    "c:headerFooter", "c:pageMargins", "c:pageSetup", "c:userShapes", "c:clrMapOvr", "c:dLblPos",
    "c:separator", "c:showLeaderLines", "c:barChart", "c:bar3DChart", "c:lineChart", "c:line3DChart",
    "c:pieChart", "c:pie3DChart", "c:doughnutChart", "c:scatterChart", "c:areaChart", "c:area3DChart",
    "c:radarChart", "c:bubbleChart", "c:stockChart", "c:surfaceChart", "c:ofPieChart",
} | {name for name in SLIDE_HANDLED if name.startswith("a:")}


def image_size(data):
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            return image.size
    except Exception:  # noqa: BLE001 -- vector formats and unknown images have no pixel size here
        return None


def extract(path):
    return Reader(path, image_size).extract()


def raw_parts(path, slide_number=None, parts=None):
    """Return {part name: pretty XML} for a slide and the parts it uses, or for named parts."""
    package = Package(path)
    names = list(parts or [])
    if slide_number is not None:
        presentation = "ppt/presentation.xml"
        rels = package.rels(presentation)
        ids = children(child(package.xml(presentation), "p:sldIdLst"), "p:sldId")
        if not 1 <= slide_number <= len(ids):
            raise ValueError(f"the deck has {len(ids)} slides")
        slide = rels[ids[slide_number - 1].get(q("r:id"))]["target"]
        names.append(slide)
        for rel in package.rels(slide).values():
            if not rel["external"] and rel["target"].endswith(".xml"):
                names.append(rel["target"])
                for inner in package.rels(rel["target"]).values():
                    if rel["type"] in ("chart", "diagramData") and not inner["external"] \
                            and inner["target"].endswith(".xml"):
                        names.append(inner["target"])
    result = {}
    for name in dict.fromkeys(names):
        root = package.xml(name)
        if root is None:
            result[name] = None if name not in package.names else f"<binary part, {len(package.blob(name))} bytes>"
        else:
            result[name] = etree.tostring(root, pretty_print=True, encoding="unicode")
        rels_name = posixpath.join(posixpath.dirname(name), "_rels", posixpath.basename(name) + ".rels")
        if rels_name in package.names:
            result[rels_name] = etree.tostring(package.xml(rels_name), pretty_print=True, encoding="unicode")
    return result
