"""Namespace resolution: what the name under the cursor refers to."""

SRC = '''import math
import numpy as np
from json import dumps


class Circle:
    radius: float = 1.0

    def area(self):
        self.cached = math.pi * self.radius ** 2
        return self.cached


def main():
    c = Circle(2)
    print(c.area())
    print(math.pi)
    print(np.array([1]))
    print(dumps({}))
'''


def _at(analyzer, needle, ch):
    for i, line in enumerate(SRC.splitlines(), 1):
        if needle in line:
            return analyzer.resolve_namespace(SRC, i, line.index(ch))
    raise AssertionError(needle)


def test_module_attribute_resolves_to_module(analyzer):
    ref = _at(analyzer, "print(math.pi)", "pi")
    assert ref.kind == "module" and ref.module == "math"


def test_import_alias_is_followed(analyzer):
    ref = _at(analyzer, "np.array([1])", "array")
    assert ref.kind == "module" and ref.module == "numpy"


def test_cursor_on_the_module_name_itself(analyzer):
    ref = _at(analyzer, "import math", "math")
    assert ref.kind == "module" and ref.module == "math"


def test_self_resolves_to_enclosing_class(analyzer):
    ref = _at(analyzer, "self.radius ** 2", "radius")
    assert ref.kind == "namespace"
    names = {m.name for m in ref.members}
    assert {"area", "radius", "cached"} <= names


def test_local_instance_infers_class(analyzer):
    ref = _at(analyzer, "c.area()", "area")
    assert ref.kind == "namespace"
    assert "area" in {m.name for m in ref.members}


def test_from_import_points_at_source_module(analyzer):
    ref = _at(analyzer, "dumps({})", "dumps")
    assert ref is not None and ref.module == "json" and ref.from_import


def test_plain_keyword_or_literal_resolves_to_nothing(analyzer):
    assert analyzer.resolve_namespace("x = 1 + 2\n", 1, 6) is None


def test_module_members_from_bundled_data(analyzer):
    members = analyzer.module_members("math")
    assert members is not None
    names = {m.name for m in members}
    assert "pi" in names and "sqrt" in names
    assert analyzer.module_members("definitely_not_a_module") is None


def test_is_stdlib(analyzer):
    assert analyzer.is_stdlib("math") and analyzer.is_stdlib("os.path")
    assert not analyzer.is_stdlib("numpy")


def test_tokens_carry_module_ref(analyzer):
    refs = {t.ref for t in analyzer.analyze(SRC).tokens if t.ref}
    assert refs == {"math", "numpy"}
