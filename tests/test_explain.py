from codecrawler.explain import CHAR, LINE


def _pos(source, needle, ch):
    for i, line in enumerate(source.splitlines(), 1):
        if needle in line:
            return i, line.index(ch)
    raise AssertionError(needle)


def test_char_mode_hit(engine, analyzer, sample_source):
    a = analyzer.analyze(sample_source)
    row, col = _pos(sample_source, "print(greet(", "(")
    ctx = engine.context(a, sample_source, row, col, CHAR)
    ex = engine.explain(ctx, sample_source)
    assert ex.found
    assert ex.matched == ("(", "OP", "call")
    assert "call" in ex.title.lower()


def test_char_mode_miss_prompts_to_ask(engine, analyzer, db):
    # remove the catch-all so an unknown token genuinely misses
    db.conn.execute("DELETE FROM entry")
    db.conn.commit()
    src = "x = 1\n"
    a = analyzer.analyze(src)
    ctx = engine.context(a, src, 1, 0, CHAR)
    ex = engine.explain(ctx, src)
    assert not ex.found
    assert "ask key" in ex.short


def test_line_mode_uses_template(engine, analyzer, sample_source):
    a = analyzer.analyze(sample_source)
    for i, line in enumerate(sample_source.splitlines(), 1):
        if "import math" in line:
            ctx = engine.context(a, sample_source, i, 0, LINE)
            ex = engine.explain(ctx, sample_source)
            assert ex.found and ex.source == "template"
            assert "Imports the module" in ex.short
            return
    raise AssertionError


def test_save_entry_persists_as_ai(engine, analyzer, db, sample_source):
    a = analyzer.analyze(sample_source)
    row, col = _pos(sample_source, "def greet", "(")
    ctx = engine.context(a, sample_source, row, col, CHAR)
    engine.save_entry(ctx, "Custom title", "custom short", "custom long", "f(x)")
    hit = db.lookup("python", ctx.lexeme, ctx.token_type, ctx.role)
    assert hit.title == "Custom title" and hit.source == "ai"


def test_save_note_for_line_mode(engine, analyzer, db, sample_source):
    a = analyzer.analyze(sample_source)
    ctx = engine.context(a, sample_source, 3, 0, LINE)
    engine.save_note(ctx, "a hand-written note about line 3")
    assert db.notes("python")
