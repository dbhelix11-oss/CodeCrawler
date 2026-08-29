"""Tie the analyzer and the database together into what the UI shows.

The engine takes a cursor position, asks the analyzer what token is there (and
what role it plays), then resolves an :class:`Explanation` — from the database in
character mode, or from the analyzer's line templates in line mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .db import Concept, Database, Entry
from .languages import Analysis, Analyzer, Token

CHAR = "char"
LINE = "line"


@dataclass
class CursorContext:
    language: str
    mode: str
    row: int  # 1-based
    col: int  # 0-based
    lineno: int
    line_text: str
    token: Token | None
    lexeme: str
    token_type: str
    role: str
    note: str
    concepts: list[str] = field(default_factory=list)  # background-concept slugs
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)

    @property
    def char_under_cursor(self) -> str:
        if 0 <= self.col < len(self.line_text):
            return self.line_text[self.col]
        return ""


@dataclass
class SiblingList:
    """The "namespace" panel: what else lives beside the name under the cursor."""

    owner: str  # "math", "self → Circle", …
    tier: int  # 0 untrusted · 1 in-file · 2 stdlib data · 3 source read · 4 import
    trusted: bool
    names: list[str] = field(default_factory=list)  # display-ordered, capped
    total: int = 0  # full count before the cap
    hint: str = ""  # e.g. how to see more, or a re-confirm nudge


@dataclass
class Explanation:
    mode: str
    found: bool
    title: str
    short: str
    long: str = ""
    example: str = ""
    source: str = ""
    matched: tuple[str, str, str] | None = None  # (lexeme, token_type, role) that hit
    subject: str = ""  # short label of what is under the cursor
    concept_slugs: list[str] = field(default_factory=list)
    concepts: list[Concept] = field(default_factory=list)
    siblings: "SiblingList | None" = None

    @property
    def header(self) -> str:
        subj = self.subject or "?"
        return f"{subj} — {self.title}" if self.title else subj


class ExplanationEngine:
    def __init__(self, db: Database, analyzer: Analyzer):
        self.db = db
        self.analyzer = analyzer

    # -- context ------------------------------------------------------

    def context(
        self,
        analysis: Analysis,
        source: str,
        row: int,
        col: int,
        mode: str,
        context_lines: int = 3,
    ) -> CursorContext:
        lines = source.splitlines()
        line_text = lines[row - 1] if 1 <= row <= len(lines) else ""
        tok = analysis.token_at(row, col)
        lexeme = tok.lexeme if tok else ""
        token_type = tok.type if tok else ""
        role = tok.role if tok else ""
        note = tok.note if tok else ""
        if mode == LINE:
            slugs = list(self.analyzer.line_concepts(source, row))
        else:
            slugs = list(tok.concepts) if tok else []
        before = lines[max(0, row - 1 - context_lines) : row - 1]
        after = lines[row : row + context_lines]
        return CursorContext(
            language=self.analyzer.name,
            mode=mode,
            row=row,
            col=col,
            lineno=row,
            line_text=line_text,
            token=tok,
            lexeme=lexeme,
            token_type=token_type,
            role=role,
            note=note,
            concepts=slugs,
            before=before,
            after=after,
        )

    # -- explanation ------------------------------------------------

    def explain(self, ctx: CursorContext, source: str) -> Explanation:
        if ctx.mode == LINE:
            ex = self._explain_line(ctx, source)
        else:
            ex = self._explain_char(ctx)
        ex.concept_slugs = list(ctx.concepts)
        ex.concepts = self.db.get_concepts(ctx.concepts, ctx.language)
        return ex

    def _subject_for(self, ctx: CursorContext) -> str:
        tok = ctx.token
        if tok is None:
            ch = ctx.char_under_cursor
            return repr(ch) if ch.strip() else "whitespace"
        if tok.type in ("NEWLINE", "NL"):
            return "line break"
        if tok.type == "INDENT":
            return "indent"
        if tok.type == "DEDENT":
            return "dedent"
        shown = tok.string if len(tok.string) <= 24 else tok.string[:23] + "…"
        tag = tok.type
        if tok.role:
            tag += "/" + tok.role
        return f"`{shown}` [{tag}]"

    def _explain_char(self, ctx: CursorContext) -> Explanation:
        subject = self._subject_for(ctx)
        if ctx.token is None:
            return Explanation(
                mode=CHAR,
                found=False,
                title="",
                short="The cursor is on whitespace between tokens — nothing to explain here.",
                subject=subject,
            )
        entry = self.db.lookup(ctx.language, ctx.lexeme, ctx.token_type, ctx.role)
        if entry is None:
            return Explanation(
                mode=CHAR,
                found=False,
                title="",
                short=(
                    f"No database entry for {subject} yet. "
                    f"Press the ask key to get an explanation and save it."
                ),
                subject=subject,
            )
        short = entry.short
        if ctx.note and ctx.note not in short:
            short = f"{short} (Here: {ctx.note}.)"
        return Explanation(
            mode=CHAR,
            found=True,
            title=entry.title,
            short=short,
            long=entry.long,
            example=entry.example,
            source=entry.source,
            matched=(entry.lexeme, entry.token_type, entry.role),
            subject=subject,
        )

    def _explain_line(self, ctx: CursorContext, source: str) -> Explanation:
        sentence = self.analyzer.describe_line(source, ctx.lineno)
        return Explanation(
            mode=LINE,
            found=True,
            title=f"Line {ctx.lineno}",
            short=sentence,
            source="template",
            subject=f"line {ctx.lineno}",
        )

    # -- saving AI answers -------------------------------------------

    def save_entry(
        self,
        ctx: CursorContext,
        title: str,
        short: str,
        long: str = "",
        example: str = "",
    ) -> Entry:
        """Persist an explanation for the token currently under the cursor."""
        lexeme = ctx.lexeme
        token_type = ctx.token_type or (ctx.token.type if ctx.token else "")
        role = ctx.role
        entry = Entry(
            language=ctx.language,
            lexeme=lexeme,
            token_type=token_type,
            role=role,
            title=title.strip(),
            short=short.strip(),
            long=long.strip(),
            example=example.strip(),
            source="ai",
        )
        self.db.upsert_entry(entry)
        return entry

    def save_note(self, ctx: CursorContext, body: str) -> None:
        topic = f"line {ctx.lineno}: {ctx.line_text.strip()[:60]}"
        self.db.add_note(ctx.language, topic, body.strip(), source="ai")
