from codecrawler.db import Concept, Database
from codecrawler.explain import CHAR, LINE
from codecrawler.languages import get


def test_concepts_seeded(db):
    assert db.count_concepts() == 20
    c = db.get_concept("function-call")
    assert c is not None and c.language == "" and "arguments" in c.body


def test_concept_language_override(tmp_path):
    d = Database(tmp_path / "x.db")
    d.bootstrap()
    d.upsert_concept(Concept(slug="function-call", title="C calls", body="in C ...", language="c"))
    assert d.get_concept("function-call", "c").title == "C calls"      # override wins
    assert d.get_concept("function-call", "python").title == "What a call is"  # falls back
    assert d.get_concept("function-call").language == ""


def test_seed_concepts_is_idempotent(tmp_path):
    d = Database(tmp_path / "x.db")
    assert d.seed_concepts_if_empty() == 20
    assert d.seed_concepts_if_empty() == 0


def test_token_concepts(analyzer, sample_source):
    a = analyzer.analyze(sample_source)
    for i, line in enumerate(sample_source.splitlines(), 1):
        if "print(greet(" in line:
            tok = a.token_at(i, line.index("("))
            assert "function-call" in tok.concepts
            return
    raise AssertionError


def test_line_concepts(analyzer, sample_source):
    for i, line in enumerate(sample_source.splitlines(), 1):
        if line.startswith("def greet"):
            slugs = analyzer.line_concepts(sample_source, i)
            assert "definition-vs-execution" in slugs
            assert "argument-vs-parameter" in slugs
        if line.strip().startswith("for radius"):
            assert "iteration-and-iterables" in analyzer.line_concepts(sample_source, i)


def test_engine_attaches_resolved_concepts(engine, analyzer, sample_source):
    a = analyzer.analyze(sample_source)
    for i, line in enumerate(sample_source.splitlines(), 1):
        if line.strip().startswith("for radius"):
            ctx = engine.context(a, sample_source, i, 0, LINE)
            ex = engine.explain(ctx, sample_source)
            assert "iteration-and-iterables" in ex.concept_slugs
            assert any(c.slug == "iteration-and-iterables" for c in ex.concepts)
            return
    raise AssertionError
