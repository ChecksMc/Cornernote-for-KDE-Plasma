"""Render a small, safe Markdown subset as text and Unicode style ranges.

Supported blocks are ATX headings, fenced code, quotes, and lists. Inline
formatting includes bold, italic, ``<u>`` underline, strikethrough, code, links,
and backslash escapes. Other HTML stays literal; no HTML, URLs, or code execute.
The result is independent of GTK and can be applied to a Gtk.TextBuffer with
``get_iter_at_offset`` and named text tags. ``spans`` addresses rendered text;
``source_spans`` addresses original Markdown for styling an editable buffer.
Source Markdown is never modified.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class Span:
    """Style a half-open range of Unicode characters."""

    start: int
    end: int
    kind: str


@dataclass(frozen=True, slots=True)
class RenderedMarkdown:
    """Display text plus formatting ranges in display and source coordinates."""

    text: str
    spans: tuple[Span, ...]
    source_spans: tuple[Span, ...] = ()


_INLINE = (
    ("bold", re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1(?![*_])"), 2),
    ("italic", re.compile(r"\*(?!\*)(?=\S)((?:\*\*.+?\*\*|[^*])+?)(?<=\S)\*(?!\*)"), 1),
    ("italic", re.compile(r"_(?!_)(?=\S)((?:__.+?__|[^_])+?)(?<=\S)_(?!_)"), 1),
    ("underline", re.compile(r"<u>(.+?)</u>", re.IGNORECASE), 1),
    ("strikethrough", re.compile(r"~~(?=\S)(.+?)(?<=\S)~~"), 1),
    ("link", re.compile(r"!?\[([^\[\]\n]+)\]\((?:[^()\s]|\([^()]*\))+?(?:\s+\"[^\"]*\")?\)"), 1),
)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*)$")
_BULLET = re.compile(r"^( {0,3})[-+*][ \t]+(.*)$")
_QUOTE = re.compile(r"^ {0,3}>[ \t]?(.*)$")
_ESCAPABLE = r"\`*_{}[]()#+-.!>~"
_LITERAL = re.compile(r"\\[\\`*_{}\[\]()#+\-.!>~]|`+")
_SPECIAL = re.compile(r"[\\`*_<!\[~]")


def _mask_literals(source: str) -> tuple[str, dict[int, tuple[int, int, int]]]:
    """Shield escapes and whole code spans from formatting delimiter searches.

    Pair equal backtick runs in one pass so unmatched runs do not repeatedly
    search the remainder of a long draft. Masking keeps original offsets.
    """
    tokens = list(_LITERAL.finditer(source))
    next_run: dict[int, int] = {}
    next_by_length: dict[int, int] = {}
    for index in range(len(tokens) - 1, -1, -1):
        token = tokens[index]
        if source[token.start()] != "`":
            continue
        length = token.end() - token.start()
        if length in next_by_length:
            next_run[index] = next_by_length[length]
        next_by_length[length] = index

    code: dict[int, tuple[int, int, int]] = {}
    parts: list[str] = []
    previous = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        end = token.end()
        if source[token.start()] == "`":
            closing_index = next_run.get(index)
            if closing_index is None:
                index += 1
                continue
            closing = tokens[closing_index]
            code[token.start()] = (token.end(), closing.start(), closing.end())
            end = closing.end()
            index = closing_index
        parts.extend((source[previous:token.start()], "\0" * (end - token.start())))
        previous = end
        index += 1
    parts.append(source[previous:])
    return "".join(parts), code


class _Output:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.spans: list[Span] = []
        self.source_spans: list[Span] = []
        self.length = 0

    def add(self, text: str) -> None:
        self.parts.append(text)
        self.length += len(text)

    def style(self, start: int, kind: str) -> None:
        if self.length > start:
            self.spans.append(Span(start, self.length, kind))

    def source_style(self, start: int, end: int, kind: str) -> None:
        if end > start:
            self.source_spans.append(Span(start, end, kind))

    def inline(self, source: str, source_start: int, depth: int = 0) -> None:
        # Limit recursion for unusually deeply nested user-authored input.
        if depth >= 32:
            self.add(source)
            return
        masked, code = _mask_literals(source)
        last_underline_close = masked.lower().rfind("</u>")
        index = 0
        while index < len(source):
            char = source[index]
            if char == "\\" and index + 1 < len(source) and source[index + 1] in _ESCAPABLE:
                self.add(source[index + 1])
                index += 2
                continue
            if char == "`":
                end = index + 1
                while end < len(source) and source[end] == "`":
                    end += 1
                if index in code:
                    end, closing, closing_end = code[index]
                    literal = source[end:closing]
                    padding = 0
                    if literal.startswith(" ") and literal.endswith(" ") and literal.strip():
                        literal = literal[1:-1]
                        padding = 1
                    start = self.length
                    self.add(literal)
                    self.style(start, "code")
                    self.source_style(source_start + end + padding,
                                      source_start + closing - padding, "code")
                    index = closing_end
                    continue
                self.add(source[index:end])
                index = end
                continue
            matched = False
            for kind, pattern, group in _INLINE:
                # Underscores within words are ordinary filename/text characters.
                if char == "_" and index and source[index - 1].isalnum():
                    continue
                if kind == "underline" and index >= last_underline_close:
                    continue
                match = pattern.match(masked, index)
                if match is None:
                    continue
                inner = source[match.start(group):match.end(group)]
                if kind in ("bold", "italic", "strikethrough") and not inner.strip("*_~"):
                    continue
                start = self.length
                self.inline(inner, source_start + match.start(group), depth + 1)
                self.style(start, kind)
                self.source_style(source_start + match.start(group),
                                  source_start + match.end(group), kind)
                index = match.end()
                matched = True
                break
            if not matched:
                end = index + 1
                if char in "*_~":
                    while end < len(source) and source[end] == char:
                        end += 1
                elif char not in "\\`<![":
                    following = _SPECIAL.search(source, end)
                    end = following.start() if following else len(source)
                self.add(source[index:end])
                index = end


def render_markdown(source: str) -> RenderedMarkdown:
    """Return readable text and style spans without interpreting arbitrary HTML.

    This deliberately implements the formatting useful in a quick-note overlay,
    rather than all of CommonMark or Obsidian extensions. Unmatched inline
    markers remain visible so unfinished drafts do not lose their text.
    """
    output = _Output()
    fence: str | None = None
    code_start = 0
    source_code_start = 0
    source_offset = 0
    for raw_line in source.splitlines(keepends=True):
        line_start = source_offset
        source_offset += len(raw_line)
        newline = "\n" if raw_line.endswith(("\n", "\r")) else ""
        line = raw_line.rstrip("\r\n")
        candidate = _FENCE.match(line)
        if fence is not None:
            if (candidate and candidate[1][0] == fence[0]
                    and len(candidate[1]) >= len(fence) and not candidate[2].strip()):
                output.style(code_start, "code_block")
                output.source_style(source_code_start, line_start, "code_block")
                fence = None
            else:
                output.add(line + newline)
            continue
        if candidate:
            fence = candidate[1]
            code_start = output.length
            source_code_start = source_offset
            continue

        start = output.length
        quoted = False
        while quote := _QUOTE.match(line):
            quoted = True
            line_start += quote.start(1)
            line = quote[1]
        quote_start = line_start
        quote_end = line_start + len(line)
        heading = _HEADING.match(line)
        if heading:
            line_start += heading.start(2)
            line = re.sub(r"[ \t]+#+[ \t]*$", "", heading[2])
        elif bullet := _BULLET.match(line):
            output.add(bullet[1] + "• ")
            line_start += bullet.start(2)
            line = bullet[2]
        output.inline(line, line_start)
        if heading:
            output.style(start, f"heading{len(heading[1])}")
            output.source_style(line_start, line_start + len(line), f"heading{len(heading[1])}")
        if quoted:
            output.style(start, "quote")
            output.source_style(quote_start, quote_end, "quote")
        output.add(newline)
    if fence is not None:
        output.style(code_start, "code_block")
        output.source_style(source_code_start, len(source), "code_block")
    return RenderedMarkdown("".join(output.parts), tuple(output.spans), tuple(output.source_spans))
