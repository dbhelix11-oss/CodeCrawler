"""Pure helpers for laying text into the fixed panes (no curses calls here)."""

from __future__ import annotations

import textwrap

# ---------------------------------------------------------------------------
# syntax highlighting — pure token -> style-name mapping
# ---------------------------------------------------------------------------

# The style names, in the order the curses layer assigns colour-pair numbers.
STYLES: tuple[str, ...] = (
    "keyword",
    "string",
    "comment",
    "number",
    "call",
    "definition",
    "decorator",
    "operator",
    "name",
    "untrusted",  # a reference to a module that is not trusted yet — shown dim
)

_STYLE_BY_TYPE = {
    "KEYWORD": "keyword",
    "STRING": "string",
    "COMMENT": "comment",
    "NUMBER": "number",
    "OP": "operator",
}

_LAYOUT_TYPES = {"NEWLINE", "NL", "INDENT", "DEDENT", "ENDMARKER"}


def token_style(token_type: str, role: str = "") -> str:
    """Map a token's normalized type + AST role to one of :data:`STYLES`."""
    if token_type == "NAME":
        if role == "definition":
            return "definition"
        if role == "call":
            return "call"
    if role == "decorator":
        return "decorator"
    return _STYLE_BY_TYPE.get(token_type, "name")


def highlight_spans(
    tokens, lineno: int, line_len: int, dim_refs=()
) -> list[tuple[int, int, str]]:
    """``(start_col, end_col, style)`` spans for one source line.

    Columns are 0-based indices into the *raw* (pre-tab-expand) line text. Only
    token extents are covered; gaps (indentation, inter-token spaces) are left
    for the caller to draw plain. A token spanning several physical lines (a
    triple-quoted string, say) contributes the slice that falls on ``lineno``.

    A token whose ``.ref`` (the module it names) is in ``dim_refs`` gets the
    ``"untrusted"`` style instead of its syntactic one.
    """
    spans: list[tuple[int, int, str]] = []
    for t in tokens:
        if t.start[0] > lineno or t.end[0] < lineno or t.type in _LAYOUT_TYPES:
            continue
        c0 = t.start[1] if t.start[0] == lineno else 0
        c1 = t.end[1] if t.end[0] == lineno else line_len
        c0 = max(0, min(c0, line_len))
        c1 = max(c0, min(c1, line_len))
        if c1 <= c0:
            continue
        ref = getattr(t, "ref", "")
        style = "untrusted" if ref and ref in dim_refs else token_style(t.type, t.role)
        spans.append((c0, c1, style))
    return spans


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

    if verbosity >= 2 and explanation.siblings is not None:
        lines.append("")
        lines.extend(_siblings_lines(explanation.siblings, width))

    if verbosity >= 2 and explanation.matched and explanation.source:
        lex, tt, role = explanation.matched
        lines.append("")
        lines.extend(
            wrap(f"[matched {lex or '*'}/{tt or '*'}/{role or '-'} · {explanation.source}]", width)
        )
    return lines


_TIER_LABEL = {
    1: "in this file",
    2: "standard library",
    3: "read from source",
    4: "imported",
}


def _siblings_lines(sib, width: int) -> list[str]:
    """Render the namespace panel — the "math also defines: …" section."""
    if not sib.trusted:
        if sib.hint:
            return wrap(f"{sib.owner} — {sib.hint}", width)
        return wrap(
            f"{sib.owner} — not trusted, so its contents are hidden.  "
            f"press t to read its source · Ctrl-t to import it",
            width,
        )
    if not sib.names:
        msg = f"{sib.owner}: nothing to list"
        if sib.hint:
            msg += f"  ({sib.hint})"
        return wrap(msg, width)
    label = _TIER_LABEL.get(sib.tier, "")
    head = f"{sib.owner} also defines" + (f" [{label}]" if label else "") + ":"
    out = wrap(head, width)
    body = "  ".join(sib.names)
    if sib.total > len(sib.names):
        body += f"   (+{sib.total - len(sib.names)} more)"
    out.extend(wrap(body, width))
    if sib.hint:
        out.extend(wrap(sib.hint, width))
    return out


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
