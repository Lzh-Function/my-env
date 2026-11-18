"""Turn an archived conversation (conversation.md) into a note that reads well in Obsidian.

The archive itself is not changed; this only shapes what `history export-md` writes:
tool calls and metadata go into collapsed callouts, turn headings get a short local time,
and headings or #tags inside messages no longer leak into the outline or tag list.
"""

import html
import json
import os
import re
from datetime import datetime, timedelta, timezone

# Bump when the note layout changes so export-md rewrites notes it wrote earlier.
FORMAT = 4

TURN = re.compile(r"### (User|Assistant) · (.*)")
SESSION = re.compile(r"## Session: (.*) \((worker|reviewer), (codex|claude)\)")
REVIEW = re.compile(r"## Review: (.*)")
REVIEW_FILE = re.compile(r"### (conversation\.md|review_findings\.json|response\.json)")
SUMMARY = re.compile(r"<summary>(.*)</summary>")
FENCE_OPEN = re.compile(r"(`{3,})(\S*)")
COMPACTED = "_Context compacted; original records above remain part of this archive._"
EMPTY = "No persisted conversation records were found."
# Messages the CLIs inject as "user" turns; they are not what the person typed.
INJECTED = re.compile(r"\s*(?:<[a-z_]+>|# AGENTS\.md instructions)")

TEXT_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
HEADING = re.compile(r" {0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*")
CODE_SPAN = re.compile(r"(`+)(?!`).*?(?<!`)\1(?!`)")
TAG = re.compile(r"(?<!\S)#(?=[^\s#])")
NAMES = {"claude": "Claude", "codex": "Codex"}
ROLES = {"worker": "作業担当", "reviewer": "監査役"}
REVIEW_FILES = {"conversation.md": ("quote", "監査のやり取り"),
                "review_findings.json": ("abstract", "監査の指摘"),
                "response.json": ("abstract", "指摘への返答")}


def zone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(os.environ.get("AGENTRUN_TIMEZONE") or "Asia/Tokyo")
    except Exception:  # noqa: BLE001 - no tz database: fall back to JST
        return timezone(timedelta(hours=9))


def short_time(stamp, tz):
    try:
        moment = datetime.fromisoformat(stamp.strip().replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz).strftime("%m/%d %H:%M")


def take_fence(lines, start):
    """(mark, language, content lines, next index) for the archive fence opening at start."""
    match = FENCE_OPEN.fullmatch(lines[start]) if start < len(lines) else None
    if not match:
        return None
    try:
        end = lines.index(match.group(1), start + 1)  # the archive's mark is longer than any run inside
    except ValueError:
        return None
    return match.group(1), match.group(2), lines[start + 1:end], end + 1


def tokens(markdown):
    """Split the archive into its structural pieces; everything else is message text."""
    lines = markdown.split("\n")
    text, index = [], 0

    def flush():
        nonlocal text
        if text:
            yield ("text", text)
        text = []

    while index < len(lines):
        line = lines[index]
        nxt = lines[index + 1] if index + 1 < len(lines) else None
        found = None
        if line == "<details>" and nxt is not None and SUMMARY.fullmatch(nxt) and index + 2 < len(lines) \
                and lines[index + 2] == "":
            fence = take_fence(lines, index + 3)
            end = fence[3] if fence else len(lines)
            if end < len(lines) and lines[end] == "":
                end += 1  # history_export writes a blank line before the closing tag
            if fence and end < len(lines) and lines[end] == "</details>":
                label = html.unescape(SUMMARY.fullmatch(nxt).group(1))
                found = (("detail", label, fence), end + 1)
        elif nxt == "" and (SESSION.fullmatch(line) or REVIEW.fullmatch(line) or REVIEW_FILE.fullmatch(line)):
            fence = take_fence(lines, index + 2)
            if fence:
                for kind, pattern in (("session", SESSION), ("review", REVIEW), ("review-file", REVIEW_FILE)):
                    match = pattern.fullmatch(line)
                    if match:
                        found = ((kind, match.groups(), fence), fence[3])
                        break
        elif TURN.fullmatch(line):
            found = (("turn",) + TURN.fullmatch(line).groups(), index + 1)
        elif line == "## Archive notes":
            found = (("heading", "## アーカイブの注記"), index + 1)
        elif line == COMPACTED:
            found = (("compacted",), index + 1)
        if found:
            yield from flush()
            yield found[0]
            index = found[1]
        else:
            text.append(line)
            index += 1
    yield from flush()


def trimmed(lines):
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def plain(text):
    text = TAG.sub(r"\\#", text)
    return text.replace("[[", r"\[\[").replace("%%", r"\%\%")


def inline(line):
    parts, last = [], 0
    for match in CODE_SPAN.finditer(line):
        parts += [plain(line[last:match.start()]), match.group()]
        last = match.end()
    return "".join(parts) + plain(line[last:])


def readable(lines):
    """Message text with headings turned into bold lines and accidental tags/links escaped."""
    out, fence = [], None
    for line in lines:
        opening = TEXT_FENCE.match(line)
        if fence:
            # Code is kept as is, except a line that would read as a block marker gets one leading space.
            out.append(" " + line if line.startswith("%% agentrun:") else line)
            closing = re.fullmatch(r" {0,3}(`{3,}|~{3,})[ \t]*", line)
            if closing and closing.group(1)[0] == fence[0] and len(closing.group(1)) >= len(fence):
                fence = None
        elif opening:
            fence = opening.group(1)
            out.append(line)
        elif HEADING.fullmatch(line):
            out.append("**" + inline(HEADING.fullmatch(line).group(1)) + "**")
        else:
            out.append(inline(line))
    if fence:
        out.append(fence)  # an unclosed block would swallow the rest of the note
    return out


def code(mark, language, content):
    return [mark + language, *content, mark]


def callout(kind, title, lines, folded=True):
    title = " ".join(title.split())
    head = f"> [!{kind}]{'-' if folded else ''} {title}"
    return [head, *(("> " + line) if line else ">" for line in lines)]


def detail(label, fence, tz):
    mark, language, content, _ = fence
    parts = [part.strip() for part in label.split(" · ")]
    when = next((short_time(p, tz) for p in reversed(parts) if short_time(p, tz)), "")
    suffix = f" · {when}" if when else ""
    kind = "example"
    if parts[0].startswith("Tool call: "):
        title = "🔧 " + parts[0][len("Tool call: "):]
    elif parts[0].startswith("Tool result: "):
        title = "↩️ 結果: " + parts[0][len("Tool result: "):]
        kind = "quote"
        if content and content[0] in ("is_error: True", "is_error: true"):
            kind, title = "failure", title + "（エラー）"
        if content and content[0].startswith("is_error: "):
            content = content[2:] if len(content) > 1 and not content[1] else content[1:]
    elif parts[0] == "Command execution":
        title = "💻 コマンド"
        try:
            command = json.JSONDecoder().raw_decode("\n".join(content))[0].get("command")
        except (ValueError, AttributeError):
            command = None
        if command:
            command = " ".join(command) if isinstance(command, list) else str(command)
            title += ": " + (command if len(command) <= 60 else command[:59] + "…")
    elif parts[0] == "File changes":
        title = "📝 ファイル変更"
    else:
        title = label
    return callout(kind, title + suffix, code(mark, language, content))


# Each folded block sits between these lines, so tools can drop them without parsing callouts.
# They are Obsidian comments (hidden when reading), and messages cannot contain them: plain()
# escapes "%%" in message text. Keep the wording stable; agents and scripts match on it.
BEGIN = "%% agentrun:begin {} %%"
END = "%% agentrun:end %%"
# An HTML comment (hidden in Obsidian, unlike %% it may contain "%%") telling a reader how to skip them.
GUIDE = ("<!-- agentrun: このノートの会話以外の部分（ツールの呼び出しと結果、コマンド出力、セッション情報、"
         "自動で挿入されたメッセージ、相互監査の詳細）は、行頭の \"%% agentrun:begin <種類> %%\" の行から "
         "\"%% agentrun:end %%\" の行までに入っています。種類は tool, session, injected, review です。"
         "会話だけを読むときは次で除けます: sed '/^%% agentrun:begin /,/^%% agentrun:end %%$/d' NOTE.md -->")


def folded(kind, block):
    """A collapsed block wrapped in markers; blank lines keep the markers out of the callout."""
    return [[BEGIN.format(kind)], block, [END]]


def obsidian_body(markdown, tz=None):
    tz = tz or zone()
    items = list(tokens(markdown))
    out, provider, index = [[GUIDE]], "claude", 0
    while index < len(items):
        item = items[index]
        kind = item[0]
        following = items[index + 1] if index + 1 < len(items) else None
        if kind == "session":
            (_stem, role, provider), fence = item[1], item[2]
            out.append([f"## {ROLES[role]}のセッション（{NAMES[provider]}）"])
            out += folded("session", callout("info", "セッション情報", code(*fence[:3])))
        elif kind == "review":
            out.append([f"## 相互監査: {item[1][0]}"])
            out += folded("review", callout("info", "監査の状態", code(*item[2][:3])))
        elif kind == "review-file":
            name, (mark, language, content, _) = item[1][0], item[2]
            style, label = REVIEW_FILES[name]
            body = readable(trimmed(content)) if language == "markdown" else code(mark, language, content)
            out += folded("review", callout(style, f"{label}（{name}）", body))
        elif kind == "turn":
            role, stamp = item[1], item[2]
            when = short_time(stamp, tz)
            suffix = f" · {when}" if when else ""
            body = trimmed(following[1]) if following and following[0] == "text" else []
            if body and following:
                index += 1
            if role == "User" and body and INJECTED.match("\n".join(body)):
                out += folded("injected", callout("note", "⚙️ 自動で挿入されたメッセージ" + suffix, readable(body)))
            else:
                name = "🧑 ユーザー" if role == "User" else "🤖 " + NAMES[provider]
                out.append([f"### {name}{suffix}"])
                if body:
                    out.append(readable(body))
        elif kind == "detail":
            out += folded("tool", detail(item[1], item[2], tz))
        elif kind == "heading":
            out.append([item[1]])
        elif kind == "compacted":
            out.append(callout("info", "ここで文脈が圧縮されました（それ以前の記録もこのノートに残っています）", [], folded=False))
        else:
            body = trimmed(item[1])
            if body == [EMPTY]:
                body = ["保存された会話の記録はありませんでした。"]
            if body:
                out.append(readable(body))
        index += 1
    return "\n\n".join("\n".join(block) for block in out) + "\n"
