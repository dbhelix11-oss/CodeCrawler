"""Language-agnostic pieces shared by every analyzer.

An :class:`Analyzer` turns source text into an :class:`Analysis`: a flat list of
:class:`Token` objects (each already carrying the normalized ``lexeme`` / ``role``
used to look the token up in the database) plus a ``describe_line`` method that
renders one line as an English sentence.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

# Position convention throughout CodeCrawler: (row, col) with row 1-based and
# col 0-based — the same convention Python's tokenize module uses.
Pos = tuple[int, int]


@dataclass(frozen=True)
class Token:
    type: str  # normalized: OP KEYWORD NAME NUMBER STRING COMMENT NEWLINE NL INDENT DEDENT
    string: str  # the exact source text of the token
    start: Pos
    end: Pos
    line: str = ""  # the physical source line the token starts on
    lexeme: str = ""  # normalized key for DB lookup (often == string, but not for STRING/NUMBER)
    role: str = ""  # AST-derived disambiguation, e.g. 'call' vs 'tuple' for '('
    note: str = ""  # extra human context, e.g. "the f-string ends here"
    concepts: tuple[str, ...] = ()  # background-concept slugs this token relates to

    def covers(self, row: int, col: int) -> bool:
        return self.start <= (row, col) < self.end

    @property
    def is_layout(self) -> bool:
        """True for tokens that are structure/whitespace rather than code."""
        return self.type in {"NEWLINE", "NL", "INDENT", "DEDENT", "ENDMARKER"}


@dataclass
class Analysis:
    language: str
    source: str
    tokens: list[Token]
    ok: bool = True  # False when the file could not be parsed and roles are degraded
    error: str = ""

    def token_at(self, row: int, col: int) -> Token | None:
        """The token whose span contains ``(row, col)``; ``None`` if between tokens."""
        hit: Token | None = None
        for tok in self.tokens:
            if tok.start > (row, col):
                break
            if tok.covers(row, col):
                hit = tok
        return hit

    def index_at(self, row: int, col: int) -> int | None:
        for i, tok in enumerate(self.tokens):
            if tok.covers(row, col):
                return i
        return None

    def nearest_index(self, row: int, col: int) -> int:
        """Index of the token at ``(row, col)``, or the next one after it."""
        for i, tok in enumerate(self.tokens):
            if tok.covers(row, col) or tok.start >= (row, col):
                return i
        return max(0, len(self.tokens) - 1)

    def meaningful_tokens(self) -> list[Token]:
        return [t for t in self.tokens if not t.is_layout]


class Analyzer(abc.ABC):
    """Base class for per-language analyzers."""

    name: str = ""
    extensions: tuple[str, ...] = ()

    @abc.abstractmethod
    def analyze(self, source: str) -> Analysis:
        """Tokenize ``source`` and tag each token with a lookup key + role."""

    @abc.abstractmethod
    def describe_line(self, source: str, lineno: int) -> str:
        """Return a one- or two-sentence plain-English reading of line ``lineno``."""

    def line_concepts(self, source: str, lineno: int) -> list[str]:
        """Background-concept slugs relevant to the constructs on line ``lineno``."""
        return []
