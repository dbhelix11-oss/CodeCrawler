import pytest


def _find(source, needle, ch, occurrence=0):
    for i, line in enumerate(source.splitlines(), 1):
        if needle in line:
            idx = -1
            for _ in range(occurrence + 1):
                idx = line.index(ch, idx + 1)
            return i, idx
    raise AssertionError(f"no line with {needle!r}")


def role_at(analyzer, source, needle, ch, occurrence=0):
    row, col = _find(source, needle, ch, occurrence)
    tok = analyzer.analyze(source).token_at(row, col)
    assert tok is not None, (needle, ch)
    return tok


@pytest.mark.parametrize(
    "needle, ch, expected_type, expected_role",
    [
        ("def greet", "(", "OP", "func-def-params"),
        ("def greet", "*", "OP", "kwonly-marker"),
        ("loud=False", "=", "OP", "param-default"),
        ("def area(self) -> float", "->", "OP", "return-annotation"),
        ("shapes = [Circle(r) for r", "[", "OP", "list-comp"),
        ("areas = {s.radius", "{", "OP", "dict-comp"),
        ("areas = {s.radius", ":", "OP", "dict-pair"),
        ('message = f"', 'f"', "STRING", "fstring"),
        ('message = f"', "{", "OP", "fstring-field"),
        ("print(greet(", "(", "OP", "call"),
        ("@dataclass", "@", "OP", "decorator"),
        ("return math.pi * self.radius ** 2", "*", "OP", "arithmetic"),
        ("return math.pi * self.radius ** 2", ".", "OP", "attribute"),
        ("class Circle", "Circle", "NAME", "definition"),
        ("radius: float", ":", "OP", "annotation"),
        ('if __name__ == "__main__"', "==", "OP", "comparison"),
    ],
)
def test_roles(analyzer, sample_source, needle, ch, expected_type, expected_role):
    tok = role_at(analyzer, sample_source, needle, ch)
    assert tok.type == expected_type
    assert tok.role == expected_role


def test_number_and_string_keys(analyzer):
    src = 'a = 0xFF\nb = 1_000\nc = 3.5\nd = 2j\ne = r"x"\nf = b"y"\n'
    a = analyzer.analyze(src)
    keyed = {t.lexeme: t.role for t in a.tokens if t.type in ("NUMBER", "STRING")}
    assert keyed["0x"] == "hex"
    assert keyed["_"] == "digit-separator"
    assert keyed["float"] == "float"
    assert keyed["j"] == "imaginary"
    assert keyed["r\""] == "raw"
    assert keyed["b\""] == "bytes"


@pytest.mark.parametrize(
    "needle, fragment",
    [
        ("import math", "Imports the module"),
        ("from dataclasses import", "imports"),
        ('GREETING = "hello"', "Assigns"),
        ("def greet(name", "Defines a function `greet`"),
        ("return math.pi", "Returns"),
        ("if loud:", "run the indented block"),
        ("for radius, size in", "For each item in"),
        ("class Circle", "Defines a class `Circle`"),
        ("message = message.upper()", "stores the result in"),
    ],
)
def test_describe_line(analyzer, sample_source, needle, fragment):
    for i, line in enumerate(sample_source.splitlines(), 1):
        if needle in line:
            assert fragment in analyzer.describe_line(sample_source, i)
            return
    raise AssertionError(needle)


def test_syntax_error_degrades_gracefully(analyzer):
    a = analyzer.analyze("def broken(:\n    x =\n")
    assert a.ok is False
    assert a.error
    assert a.tokens  # tokenizer still produced something


def test_token_at_between_tokens_is_none(analyzer):
    a = analyzer.analyze("x  =  1\n")
    assert a.token_at(1, 1) is None  # the space after x
    assert a.token_at(1, 0).string == "x"
