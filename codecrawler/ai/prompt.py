"""Build the question sent to Claude and parse the answer back.

Both AI paths (bridge and direct API) use :func:`build_prompt` so the wording is
identical, and both feed the reply through :func:`parse_answer`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..explain import CHAR, LINE, CursorContext

SYSTEM = (
    "You are a syntax tutor helping someone learn to READ code fluently. "
    "They know general programming but not this language's syntax in depth. "
    "Explain the exact element asked about: what it is, what it does in THIS "
    "spot, and why it is there. Be concrete and brief. No preamble, no "
    "encouragement, no restating the question."
)

_ANSWER_FORMAT = (
    "Reply using exactly this template, one field per line:\n"
    "TITLE: a short label, at most 6 words\n"
    "SHORT: one sentence explaining it in this context\n"
    "LONG: 2-4 sentences on the what/why/when\n"
    "EXAMPLE: one short line of code (or omit this line)"
)


@dataclass
class AskPrompt:
    system: str
    user: str

    @property
    def full_text(self) -> str:
        """Single blob to paste into Claude Code in bridge mode."""
        return f"{self.system}\n\n{self.user}\n"


@dataclass
class ParsedAnswer:
    title: str
    short: str
    long: str
    example: str
    raw: str

    @property
    def ok(self) -> bool:
        return bool(self.short or self.long)


def _caret_line(col: int) -> str:
    return " " * max(0, col) + "^"


_DEPTH_NOTE = {
    0: "Keep it to a single short sentence.",
    1: "One or two sentences. Assume general programming knowledge.",
    2: "A short paragraph: what it is, what it does here, and why it is there.",
    3: (
        "The reader is a beginner. Assume almost no prior knowledge and briefly "
        "define any technical term you use (callable, operand, iterable, "
        "namespace, binding, expression, statement, ...)."
    ),
}


def build_prompt(ctx: CursorContext, verbosity: int = 1) -> AskPrompt:
    ctx_before = "\n".join(ctx.before)
    ctx_after = "\n".join(ctx.after)
    lines = []
    lines.append(f"Language: {ctx.language}")
    lines.append(f"Depth: {_DEPTH_NOTE.get(verbosity, _DEPTH_NOTE[1])}")
    if ctx.concepts:
        lines.append("Related concepts: " + ", ".join(ctx.concepts))
    lines.append("")
    lines.append("Context (the marked line is line %d):" % ctx.lineno)
    lines.append("```")
    if ctx_before:
        lines.append(ctx_before)
    lines.append(ctx.line_text)
    lines.append(_caret_line(ctx.col))
    if ctx_after:
        lines.append(ctx_after)
    lines.append("```")
    lines.append("")

    if ctx.mode == LINE:
        lines.append(
            f"Explain the whole of line {ctx.lineno} in plain English: first one or "
            f"two sentences reading it aloud, then a short clause-by-clause breakdown."
        )
        lines.append("")
        lines.append(
            "Reply as:\nTITLE: Line %d\nSHORT: the one/two sentence reading\n"
            "LONG: the breakdown\nEXAMPLE: (omit)" % ctx.lineno
        )
    else:
        tok = ctx.token
        if tok is not None:
            piece = tok.string if len(tok.string) <= 40 else tok.string[:39] + "…"
            desc = f"the token `{piece}` (lexer type {tok.type}"
            if tok.role:
                desc += f", role as CodeCrawler sees it: {tok.role}"
            desc += f") at line {ctx.lineno}, column {ctx.col}"
        else:
            desc = (
                f"the character {ctx.char_under_cursor!r} at line {ctx.lineno}, "
                f"column {ctx.col} (it is between tokens / whitespace)"
            )
        lines.append(f"Explain {desc}.")
        lines.append("")
        lines.append(_ANSWER_FORMAT)

    return AskPrompt(system=SYSTEM, user="\n".join(lines))


_FIELD_RE = re.compile(
    r"^(TITLE|SHORT|LONG|EXAMPLE)\s*:\s*(.*)$", re.IGNORECASE
)


def parse_answer(text: str) -> ParsedAnswer:
    fields: dict[str, list[str]] = {"title": [], "short": [], "long": [], "example": []}
    current: str | None = None
    saw_any = False
    for line in text.splitlines():
        m = _FIELD_RE.match(line.strip())
        if m:
            current = m.group(1).lower()
            fields[current].append(m.group(2).strip())
            saw_any = True
        elif current is not None:
            fields[current].append(line.rstrip())

    def joined(key: str) -> str:
        return "\n".join(p for p in fields[key]).strip()

    if not saw_any:
        # Model ignored the template — keep everything as the short text.
        return ParsedAnswer(
            title="", short=text.strip(), long="", example="", raw=text
        )

    return ParsedAnswer(
        title=joined("title"),
        short=joined("short"),
        long=joined("long"),
        example=joined("example"),
        raw=text,
    )
