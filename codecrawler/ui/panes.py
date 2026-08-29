"""Pure helpers for laying text into the fixed panes (no curses calls here)."""

from __future__ import annotations

import textwrap


def wrap(text: str, width: int) -> list[str]:
    out: list[str] = []
    for para in text.splitlines() or [""]:
        if not para:
            out.append("")
            continue
        out.extend(
            textwrap.wrap(
                para,
                width=max(1, width),
                break_long_words=True,
                break_on_hyphens=False,
            )
            or [""]
        )
    return out


def scroll_to_show(target: int, offset: int, height: int, total: int) -> int:
    """Return a new scroll offset so row ``target`` (0-based) is visible."""
    if target < offset:
        offset = target
    elif target >= offset + height:
        offset = target - height + 1
    max_offset = max(0, total - height)
    return max(0, min(offset, max_offset))


def explanation_body(explanation, detail: bool, width: int) -> list[str]:
    """The lines shown in the explanation pane for a resolved Explanation."""
    lines = wrap(explanation.header, width)
    lines.append("")
    lines.extend(wrap(explanation.short, width))
    if detail:
        if explanation.long:
            lines.append("")
            lines.extend(wrap(explanation.long, width))
        if explanation.example:
            lines.append("")
            lines.extend(wrap("e.g.  " + explanation.example, width))
    if explanation.matched and explanation.source:
        lex, tt, role = explanation.matched
        tag = f"[matched {lex or '*'}/{tt or '*'}/{role or '-'} · {explanation.source}]"
        lines.append("")
        lines.extend(wrap(tag, width))
    return lines


def answer_body(parsed, width: int) -> list[str]:
    """The lines shown while a fetched AI answer is awaiting save/discard."""
    lines = ["Claude says:", ""]
    if parsed.title:
        lines.extend(wrap("TITLE: " + parsed.title, width))
    if parsed.short:
        lines.extend(wrap("SHORT: " + parsed.short, width))
    if parsed.long:
        lines.append("")
        lines.extend(wrap(parsed.long, width))
    if parsed.example:
        lines.append("")
        lines.extend(wrap("e.g.  " + parsed.example, width))
    lines.append("")
    lines.append("[s] save to database   [e] edit then save   [d] discard")
    return lines
