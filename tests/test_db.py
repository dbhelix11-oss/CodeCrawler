from codecrawler.db import Database, Entry, iter_bundled_seeds


def test_bundled_seed_is_wellformed():
    langs = dict(iter_bundled_seeds())
    assert "python" in langs
    records = langs["python"]
    assert len(records) >= 100
    keys = set()
    for r in records:
        assert r["title"] and r["short"], r
        key = (r["lexeme"], r["token_type"], r.get("role", ""))
        assert key not in keys, f"duplicate seed key {key}"
        keys.add(key)


def test_seed_if_empty_is_idempotent(tmp_path):
    d = Database(tmp_path / "x.db")
    first = d.seed_if_empty()
    assert first["python"] > 100
    assert d.seed_if_empty() == {}  # nothing re-seeded
    assert d.count_entries("python") == first["python"]


def test_lookup_resolution_chain(db):
    # 1. exact (lexeme, type, role)
    e = db.lookup("python", "(", "OP", "call")
    assert e is not None and e.role == "call"

    # 2. role-neutral entry when role is unknown
    e = db.lookup("python", "and", "KEYWORD", "")
    assert e is not None and "AND" in e.title.upper()

    # 3. any-role fallback: '+' has only roled entries, no ('','+','OP','')
    e = db.lookup("python", "+", "OP", "")
    assert e is not None and e.token_type == "OP"

    # 4. generic per-token-type entry for a bare identifier
    e = db.lookup("python", "", "NAME", "")
    assert e is not None and e.title == "Identifier"

    # 5. ultimate catch-all
    e = db.lookup("python", "zzz", "WAT", "")
    assert e is not None and e.lexeme == "" and e.token_type == ""


def test_upsert_overrides_and_marks_source(db):
    key = dict(language="python", lexeme="(", token_type="OP", role="call")
    db.upsert_entry(Entry(**key, title="Custom", short="my own words", source="ai"))
    e = db.lookup("python", "(", "OP", "call")
    assert e.title == "Custom" and e.source == "ai"


def test_notes_roundtrip(db):
    db.add_note("python", "line 3: import math", "it loads the math module", source="ai")
    notes = db.notes("python")
    assert notes and notes[0][0].startswith("line 3")
