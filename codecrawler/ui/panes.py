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


def explanation_body(explanation, verbosity: int, mode: str, width: int) -> list[str]:
    """The lines shown in the explanation pane, sized to the verbosity level.

    0 = header only · 1 = + one sentence · 2 = + why/example ·
    3 = + linked fundamentals (full text in line mode, a pointer in char mode).
    """
    lines = wrap(explanation.header, width)
    if verbosity <= 0:
        return lines

    lines.append("")
    lines.extend(wrap(explanation.short, width))

    if verbosity >= 2:
        if explanation.long:
            lines.append("")
            lines.extend(wrap(explanation.long, width))
        if explanation.example:
            lines.append("")
            lines.extend(wrap("e.g.  " + explanation.example, width))

    if verbosity >= 3 and explanation.concept_slugs:
        if mode == "line":
            shown = set()
            for c in explanation.concepts:
                shown.add(c.slug)
                lines.append("")
                rule = "── " + c.title + " "
                lines.append(rule + "─" * max(0, width - len(rule)))
                lines.extend(wrap(c.body, width))
            missing = [s for s in explanation.concept_slugs if s not in shown]
            if missing:
                lines.append("")
                lines.extend(
                    wrap("(no concept entry yet for: " + ", ".join(missing)
                         + " — press ? to fetch one)", width)
                )
        else:
            lines.append("")
            lines.extend(
                wrap("Fundamentals: " + ", ".join(explanation.concept_slugs)
                     + "  —  switch to line mode (m) to read them", width)
            )

    if verbosity >= 2 and explanation.matched and explanation.source:
        lex, tt, role = explanation.matched
        lines.append("")
        lines.extend(
            wrap(f"[matched {lex or '*'}/{tt or '*'}/{role or '-'} · {explanation.source}]", width)
        )
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
