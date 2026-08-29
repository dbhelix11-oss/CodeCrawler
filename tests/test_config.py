import tomllib

from codecrawler import config


def test_defaults_when_no_file(tmp_path):
    cfg = config.load(tmp_path / "nope.toml")
    assert cfg.display.verbosity == 1
    assert cfg.display.color is True
    assert cfg.trust.enabled is True
    assert cfg.trust.stdlib is True
    assert cfg.trust.allow_import is False  # the risky path is opt-in


def test_written_template_parses_and_round_trips(tmp_path):
    path = tmp_path / "config.toml"
    config.ensure_file(path)
    parsed = tomllib.loads(path.read_text())
    assert parsed["trust"]["allow_import"] is False
    cfg = config.load(path)
    assert cfg.trust.allow_import is False


def test_allow_import_can_be_turned_on(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[trust]\nallow_import = true\n")
    assert config.load(path).trust.allow_import is True


def test_verbosity_is_clamped(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[display]\nverbosity = 9\n")
    assert config.load(path).display.verbosity == config.VERBOSITY_MAX
