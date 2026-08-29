from codecrawler.ai import build_prompt, parse_answer
from codecrawler.ai import bridge
from codecrawler.explain import CHAR, LINE


def _ctx(engine, analyzer, source, needle, ch, mode=CHAR):
    a = analyzer.analyze(source)
    for i, line in enumerate(source.splitlines(), 1):
        if needle in line:
            return engine.context(a, source, i, line.index(ch), mode)
    raise AssertionError(needle)


def test_build_prompt_char_mode(engine, analyzer, sample_source):
    ctx = _ctx(engine, analyzer, sample_source, "def greet", "(")
    p = build_prompt(ctx)
    assert "Language: python" in p.user
    assert "^" in p.user  # caret marker
    assert "func-def-params" in p.user
    assert "TITLE:" in p.user
    assert p.system.startswith("You are a syntax tutor")


def test_build_prompt_line_mode(engine, analyzer, sample_source):
    ctx = _ctx(engine, analyzer, sample_source, "for radius", "f", mode=LINE)
    p = build_prompt(ctx)
    assert "whole of line" in p.user


def test_build_prompt_verbosity_and_concepts(engine, analyzer, sample_source):
    ctx = _ctx(engine, analyzer, sample_source, "print(greet(", "(")
    terse = build_prompt(ctx, verbosity=0).user
    deep = build_prompt(ctx, verbosity=3).user
    assert "single short sentence" in terse
    assert "beginner" in deep and "define any technical term" in deep
    assert "Related concepts: function-call" in deep


def test_parse_answer_template():
    text = (
        "TITLE: Call parentheses\n"
        "SHORT: they invoke the function\n"
        "LONG: first line\nsecond line\n"
        "EXAMPLE: f(x)\n"
    )
    p = parse_answer(text)
    assert p.title == "Call parentheses"
    assert p.short == "they invoke the function"
    assert "second line" in p.long
    assert p.example == "f(x)"
    assert p.ok


def test_parse_answer_without_template():
    p = parse_answer("just some freeform explanation")
    assert p.short == "just some freeform explanation"
    assert p.title == ""
    assert p.ok


def test_bridge_write_and_read_roundtrip(cfg, engine, analyzer, sample_source):
    ctx = _ctx(engine, analyzer, sample_source, "def greet", "(")
    prompt = build_prompt(ctx)
    path, _copied = bridge.write_ask(cfg, prompt)
    assert path.is_file()
    assert "func-def-params" in path.read_text()

    cfg.answer_path.write_text("TITLE: X\nSHORT: y\n")
    assert "SHORT: y" in bridge.read_answer(cfg)
    parsed = parse_answer(bridge.read_answer(cfg))
    assert parsed.title == "X"
