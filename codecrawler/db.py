"""SQLite storage for CodeCrawler's syntax database.

One database holds explanations for every language. An :class:`Entry` is keyed by
``(language, lexeme, token_type, role)``; lookups fall back from most specific to
least specific so a bare ``(lexeme, token_type)`` entry still matches when no
role-specific one exists.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = "2"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS language (
    id   INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS entry (
    id          INTEGER PRIMARY KEY,
    language_id INTEGER NOT NULL REFERENCES language(id),
    lexeme      TEXT NOT NULL,
    token_type  TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL,
    short       TEXT NOT NULL,
    long        TEXT NOT NULL DEFAULT '',
    example     TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT 'user',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(language_id, lexeme, token_type, role)
);

CREATE INDEX IF NOT EXISTS idx_entry_lookup
    ON entry(language_id, lexeme, token_type, role);

CREATE TABLE IF NOT EXISTS note (
    id          INTEGER PRIMARY KEY,
    language_id INTEGER NOT NULL REFERENCES language(id),
    topic       TEXT NOT NULL,
    body        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'user',
    created_at  TEXT NOT NULL
);

-- Reusable, mostly language-neutral background explanations. A token's analyzer
-- links it to one or more slugs; higher verbosity levels show these bodies.
CREATE TABLE IF NOT EXISTS concept (
    id         INTEGER PRIMARY KEY,
    slug       TEXT NOT NULL,
    language   TEXT NOT NULL DEFAULT '',   -- '' = applies to every language
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(slug, language)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_SEED_FIELDS = ("lexeme", "token_type", "role", "title", "short", "long", "example")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Entry:
    language: str
    lexeme: str
    token_type: str
    role: str
    title: str
    short: str
    long: str = ""
    example: str = ""
    source: str = "user"

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.language, self.lexeme, self.token_type, self.role)


@dataclass(frozen=True)
class Concept:
    slug: str
    title: str
    body: str
    language: str = ""
    source: str = "seed"


class Database:
    """A thin wrapper over a SQLite connection with CodeCrawler's schema."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_SCHEMA)
        self.conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        self.conn.commit()

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- languages -------------------------------------------------------

    def language_id(self, name: str, *, create: bool = True) -> int | None:
        row = self.conn.execute(
            "SELECT id FROM language WHERE name = ?", (name,)
        ).fetchone()
        if row is not None:
            return int(row["id"])
        if not create:
            return None
        cur = self.conn.execute("INSERT INTO language(name) VALUES (?)", (name,))
        self.conn.commit()
        return int(cur.lastrowid)

    def languages(self) -> list[str]:
        return [
            r["name"]
            for r in self.conn.execute("SELECT name FROM language ORDER BY name")
        ]

    # -- entries --------------------------------------------------------

    def upsert_entry(self, entry: Entry) -> None:
        lang_id = self.language_id(entry.language)
        now = _now()
        self.conn.execute(
            """
            INSERT INTO entry(language_id, lexeme, token_type, role, title, short,
                              long, example, source, created_at, updated_at)
            VALUES (:lang, :lexeme, :token_type, :role, :title, :short, :long,
                    :example, :source, :now, :now)
            ON CONFLICT(language_id, lexeme, token_type, role) DO UPDATE SET
                title = excluded.title,
                short = excluded.short,
                long = excluded.long,
                example = excluded.example,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            {
                "lang": lang_id,
                "lexeme": entry.lexeme,
                "token_type": entry.token_type,
                "role": entry.role,
                "title": entry.title,
                "short": entry.short,
                "long": entry.long,
                "example": entry.example,
                "source": entry.source,
                "now": now,
            },
        )
        self.conn.commit()

    def _row_to_entry(self, language: str, row: sqlite3.Row) -> Entry:
        return Entry(
            language=language,
            lexeme=row["lexeme"],
            token_type=row["token_type"],
            role=row["role"],
            title=row["title"],
            short=row["short"],
            long=row["long"],
            example=row["example"],
            source=row["source"],
        )

    def lookup(
        self, language: str, lexeme: str, token_type: str, role: str = ""
    ) -> Entry | None:
        """Resolve an entry, falling back from specific to general.

        Order:
          1. ``(lexeme, token_type, role)``      -- exact, if a role was given
          2. ``(lexeme, token_type, '')``        -- the role-neutral entry
          3. ``(lexeme, token_type, <any role>)``-- any meaning of this lexeme
          4. ``(lexeme, '', '')``                -- lexeme regardless of type
          5. ``('', token_type, '')``            -- generic per-token-type entry
          6. ``('', '', '')``                    -- catch-all

        Returns ``None`` only if even the catch-all is missing.
        """
        lang_id = self.language_id(language, create=False)
        if lang_id is None:
            return None

        def one(lex: str, tt: str, rl: str) -> Entry | None:
            row = self.conn.execute(
                "SELECT * FROM entry WHERE language_id = ? AND lexeme = ? "
                "AND token_type = ? AND role = ?",
                (lang_id, lex, tt, rl),
            ).fetchone()
            return self._row_to_entry(language, row) if row is not None else None

        if role:
            hit = one(lexeme, token_type, role)
            if hit is not None:
                return hit
        hit = one(lexeme, token_type, "")
        if hit is not None:
            return hit

        row = self.conn.execute(
            "SELECT * FROM entry WHERE language_id = ? AND lexeme = ? AND token_type = ? "
            "ORDER BY (role = '') DESC, role LIMIT 1",
            (lang_id, lexeme, token_type),
        ).fetchone()
        if row is not None:
            return self._row_to_entry(language, row)

        for lex, tt, rl in ((lexeme, "", ""), ("", token_type, ""), ("", "", "")):
            hit = one(lex, tt, rl)
            if hit is not None:
                return hit
        return None

    def all_entries(self, language: str) -> list[Entry]:
        lang_id = self.language_id(language, create=False)
        if lang_id is None:
            return []
        rows = self.conn.execute(
            """
            SELECT * FROM entry WHERE language_id = ?
            ORDER BY lexeme, token_type, role
            """,
            (lang_id,),
        ).fetchall()
        return [self._row_to_entry(language, r) for r in rows]

    def count_entries(self, language: str) -> int:
        lang_id = self.language_id(language, create=False)
        if lang_id is None:
            return 0
        return int(
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM entry WHERE language_id = ?", (lang_id,)
            ).fetchone()["n"]
        )

    # -- notes ---------------------------------------------------------

    def add_note(self, language: str, topic: str, body: str, source: str = "user") -> int:
        lang_id = self.language_id(language)
        cur = self.conn.execute(
            "INSERT INTO note(language_id, topic, body, source, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (lang_id, topic, body, source, _now()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def notes(self, language: str) -> list[tuple[str, str, str]]:
        lang_id = self.language_id(language, create=False)
        if lang_id is None:
            return []
        rows = self.conn.execute(
            "SELECT topic, body, created_at FROM note WHERE language_id = ? "
            "ORDER BY created_at",
            (lang_id,),
        ).fetchall()
        return [(r["topic"], r["body"], r["created_at"]) for r in rows]

    # -- seeding ------------------------------------------------------

    def seed_from_records(self, language: str, records: list[dict]) -> int:
        """Insert seed ``records`` for ``language``; return how many were written."""
        written = 0
        for rec in records:
            entry = Entry(
                language=language,
                lexeme=rec["lexeme"],
                token_type=rec["token_type"],
                role=rec.get("role", ""),
                title=rec["title"],
                short=rec["short"],
                long=rec.get("long", ""),
                example=rec.get("example", ""),
                source=rec.get("source", "seed"),
            )
            self.upsert_entry(entry)
            written += 1
        return written

    def seed_if_empty(self) -> dict[str, int]:
        """Load every bundled seed file for languages that have no entries yet."""
        loaded: dict[str, int] = {}
        for language, records in iter_bundled_seeds():
            if self.count_entries(language) == 0:
                loaded[language] = self.seed_from_records(language, records)
        return loaded

    # -- concepts ----------------------------------------------------

    def upsert_concept(self, concept: Concept) -> None:
        now = _now()
        self.conn.execute(
            """
            INSERT INTO concept(slug, language, title, body, source, created_at, updated_at)
            VALUES (:slug, :language, :title, :body, :source, :now, :now)
            ON CONFLICT(slug, language) DO UPDATE SET
                title = excluded.title,
                body = excluded.body,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            {
                "slug": concept.slug,
                "language": concept.language,
                "title": concept.title,
                "body": concept.body,
                "source": concept.source,
                "now": now,
            },
        )
        self.conn.commit()

    def get_concept(self, slug: str, language: str = "") -> Concept | None:
        """A language-specific concept overrides the neutral one of the same slug."""
        for lang in ((language,) if language else ()) + ("",):
            row = self.conn.execute(
                "SELECT * FROM concept WHERE slug = ? AND language = ?", (slug, lang)
            ).fetchone()
            if row is not None:
                return Concept(
                    slug=row["slug"],
                    title=row["title"],
                    body=row["body"],
                    language=row["language"],
                    source=row["source"],
                )
        return None

    def get_concepts(self, slugs, language: str = "") -> list[Concept]:
        out: list[Concept] = []
        for slug in slugs:
            c = self.get_concept(slug, language)
            if c is not None:
                out.append(c)
        return out

    def all_concepts(self) -> list[Concept]:
        rows = self.conn.execute(
            "SELECT * FROM concept ORDER BY slug, language"
        ).fetchall()
        return [
            Concept(
                slug=r["slug"],
                title=r["title"],
                body=r["body"],
                language=r["language"],
                source=r["source"],
            )
            for r in rows
        ]

    def count_concepts(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) AS n FROM concept").fetchone()["n"])

    def seed_concepts_if_empty(self) -> int:
        if self.count_concepts() > 0:
            return 0
        written = 0
        for rec in iter_bundled_concepts():
            self.upsert_concept(
                Concept(
                    slug=rec["slug"],
                    title=rec["title"],
                    body=rec["body"],
                    language=rec.get("language", ""),
                    source=rec.get("source", "seed"),
                )
            )
            written += 1
        return written

    # -- one-call setup -------------------------------------------

    def bootstrap(self) -> dict[str, int]:
        """Seed entries and concepts for anything not populated yet. Idempotent."""
        loaded = self.seed_if_empty()
        n = self.seed_concepts_if_empty()
        if n:
            loaded["concepts"] = n
        return loaded


# Bundled JSON files under seeds/ that are not per-language token seeds.
_NON_SEED_JSON = {"concepts.json", "python_stdlib.json"}


def iter_bundled_seeds():
    """Yield ``(language, records)`` for each language seed file in ``codecrawler/seeds/``."""
    seed_dir = resources.files("codecrawler").joinpath("seeds")
    for item in seed_dir.iterdir():
        if item.name.endswith(".json") and item.name not in _NON_SEED_JSON:
            language = item.name[: -len(".json")]
            records = json.loads(item.read_text(encoding="utf-8"))
            yield language, records


def iter_bundled_concepts():
    """Yield each record from the bundled ``concepts.json``."""
    path = resources.files("codecrawler").joinpath("seeds", "concepts.json")
    yield from json.loads(path.read_text(encoding="utf-8"))
