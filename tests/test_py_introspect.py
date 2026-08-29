"""Tier 3 (read source) and tier 4 (import) module introspection."""

from codecrawler.languages import py_introspect as pi


def test_read_source_members_of_a_pure_python_module():
    names = {m.name for m in (pi.read_source_members("json") or [])}
    assert {"dumps", "loads", "JSONDecoder"} <= names


def test_read_source_members_none_for_c_extension():
    # math is implemented in C — there is no .py to read.
    assert pi.read_source_members("math") is None


def test_read_source_members_declines_dotted_names():
    assert pi.read_source_members("os.path") is None


def test_import_members_runs_and_lists():
    names = {m.name for m in pi.import_members("json")}
    assert "dumps" in names
    assert all(not n.startswith("_") for n in names)


def test_module_source_file_only_for_single_file_modules():
    assert pi.module_source_file("json") is None  # json is a package
    assert pi.module_source_file("os.path") is None
    # a single-file stdlib module resolves to its .py
    p = pi.module_source_file("string")
    assert p is not None and p.name == "string.py"
