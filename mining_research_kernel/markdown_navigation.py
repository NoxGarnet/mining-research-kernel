"""Small lexical helpers for Markdown entry navigation, preserving offsets."""
from __future__ import annotations

import re


_FENCE_START = re.compile(r"^[ \t]{0,3}(?:`{3,}|~{3,})", re.M)
_TOKENS = re.compile(
    r"(?P<fence>^[ \t]{0,3}(?P<marker>`{3,}|~{3,}))|(?P<comment><!--)|(?P<ticks>`+)", re.M
)


def mask_comments_and_fences(text: str) -> str:
    """Mask comments and fenced examples without changing offsets or newlines.

    Process delimiters in source order: fences inside comments and comment
    delimiters inside code are literal. An unclosed comment/fence masks the
    remaining bounded input, including when a read cuts off its closing marker.
    """
    ticks, closers = _tick_closers(text)
    code_ends = {ticks[index].start(): ticks[closer].end()
                 for index, closer in closers.items()}
    output, copied_until, covered_until = [], 0, 0
    for token in _TOKENS.finditer(text):
        if token.start() < covered_until:
            continue
        mask_end = None
        if token.group("fence") is not None:
            fence = token.group("marker")
            line_end = text.find("\n", token.end())
            info = text[token.end():line_end if line_end >= 0 else len(text)]
            if fence[0] != "`" or "`" not in info:
                closing = re.compile(
                    r"^[ \t]{0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*\r?$",
                    re.M,
                ).search(text, token.end())
                mask_end = closing.end() if closing else len(text)
        elif token.group("comment") is not None:
            if not _escaped(text, token.start()):
                closing = text.find("-->", token.end())
                mask_end = closing + 3 if closing >= 0 else len(text)
        if mask_end is not None:
            output.append(text[copied_until:token.start()])
            output.append(re.sub(r"[^\r\n]", " ", text[token.start():mask_end]))
            copied_until = covered_until = mask_end
        elif token.group("comment") is None:
            tick_start = token.end() - len(token.group("marker") or token.group("ticks"))
            code_end = code_ends.get(tick_start)
            if (code_end is not None and not _escaped(text, tick_start)
                    and not _FENCE_START.search(text, token.end(), code_end)):
                covered_until = code_end
    output.append(text[copied_until:])
    return "".join(output)


def _escaped(text: str, offset: int) -> bool:
    start = offset
    while start and text[start - 1] == "\\":
        start -= 1
    return (offset - start) % 2 == 1


def _tick_closers(prose: str):
    """Index possible same-width closing delimiters within each paragraph."""
    ticks = list(re.finditer(r"`+", prose))
    next_width, closers = {}, {}
    for index in range(len(ticks) - 1, -1, -1):
        # Inline code cannot join otherwise separate Markdown paragraphs.
        if index + 1 < len(ticks) and re.search(
                r"\r?\n[ \t]*\r?\n", prose[ticks[index].end():ticks[index + 1].start()]):
            next_width.clear()
        width = len(ticks[index][0])
        if width in next_width:
            closers[index] = next_width[width]
        next_width[width] = index
    return ticks, closers


def inline_code_spans(prose: str) -> list[tuple[int, int, int]]:
    """Return non-overlapping (start, end, tick-width) spans in bounded prose."""
    ticks, closers = _tick_closers(prose)
    spans, covered_until = [], 0
    for index, tick in enumerate(ticks):
        if tick.start() < covered_until or _escaped(prose, tick.start()):
            continue
        if index in closers:
            covered_until = ticks[closers[index]].end()
            spans.append((tick.start(), covered_until, len(tick[0])))
    return spans


def inline_links(prose: str):
    """Yield simple inline links, excluding images, escapes and code examples.

    The caller masks comments and fenced blocks first. This is deliberately lexical; it does
    not resolve reference-style links or implement a full Markdown renderer.
    """
    spans = inline_code_spans(prose)
    span_index = 0
    for match in re.finditer(r"(?<!!)\[([^\]\n]+)\]\((<[^>\n]+>|[^\s()]+)\)", prose):
        while span_index < len(spans) and spans[span_index][1] <= match.start():
            span_index += 1
        if span_index < len(spans) and spans[span_index][0] <= match.start() < spans[span_index][1]:
            continue
        if not _escaped(prose, match.start()):
            yield match
