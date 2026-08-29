"""The per-file trust store."""

from codecrawler.trust import TIER_IMPORT, TIER_SOURCE, TrustStore, sha256_file


def test_sha256_file_reads_bytes(tmp_path):
    p = tmp_path / "a.py"
    p.write_text("print(1)\n")
    assert sha256_file(p) == sha256_file(p) != ""
    assert sha256_file(tmp_path / "missing") == ""


def test_empty_when_nothing_recorded(tmp_path):
    store = TrustStore(tmp_path / "trust.json")
    ft = store.for_file(tmp_path / "x.py")
    assert ft.file_sha256 == "" and ft.modules == {}


def test_record_then_reload(tmp_path):
    target = tmp_path / "x.py"
    target.write_text("import numpy\n")
    path = tmp_path / "trust.json"
    TrustStore(path).record(target, sha256_file(target), "numpy", TIER_SOURCE)
    TrustStore(path).record(target, sha256_file(target), "helpers", TIER_IMPORT, "abc123")

    ft = TrustStore(path).for_file(target)
    assert ft.file_sha256 == sha256_file(target)
    assert ft.modules["numpy"].tier == TIER_SOURCE
    assert ft.modules["helpers"].tier == TIER_IMPORT
    assert ft.modules["helpers"].module_sha256 == "abc123"


def test_trust_is_keyed_by_resolved_path(tmp_path):
    target = tmp_path / "x.py"
    target.write_text("x = 1\n")
    path = tmp_path / "trust.json"
    TrustStore(path).record(target, "sha", "numpy", TIER_SOURCE)
    # a different spelling of the same file still finds the entry
    weird = tmp_path / "sub" / ".." / "x.py"
    assert "numpy" in TrustStore(path).for_file(weird).modules


def test_file_hash_change_is_detectable(tmp_path):
    target = tmp_path / "x.py"
    target.write_text("import numpy\n")
    path = tmp_path / "trust.json"
    TrustStore(path).record(target, sha256_file(target), "numpy", TIER_SOURCE)

    target.write_text("import numpy\nimport os\n")  # file changed
    ft = TrustStore(path).for_file(target)
    assert ft.file_sha256 != sha256_file(target)  # caller compares and reacts


def test_forget_removes_a_module(tmp_path):
    target = tmp_path / "x.py"
    target.write_text("x = 1\n")
    path = tmp_path / "trust.json"
    s = TrustStore(path)
    s.record(target, "sha", "numpy", TIER_SOURCE)
    s.forget(target, "numpy")
    assert "numpy" not in TrustStore(path).for_file(target).modules


def test_corrupt_file_is_ignored(tmp_path):
    path = tmp_path / "trust.json"
    path.write_text("{not json")
    assert TrustStore(path).for_file(tmp_path / "x.py").modules == {}
