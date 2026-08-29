"""App-level trust behaviour that doesn't need a live terminal.

``App.__init__`` and the trust helpers touch no curses; only ``_confirm`` /
``run`` do. These tests exercise the guards that run before any prompt.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from codecrawler.config import TrustConfig
from codecrawler.explain import ExplanationEngine
from codecrawler.languages import get
from codecrawler.trust import TIER_IMPORT, TIER_SOURCE
from codecrawler.ui.app import App

SRC = "import math\nimport pytest\n\n\ndef main():\n    print(math.pi, pytest.__version__)\n"


def _app(cfg):
    an = get("python")
    return App(Path(cfg.data_dir) / "f.py", SRC, an, ExplanationEngine(_db(cfg), an), cfg)


def _db(cfg):
    from codecrawler.db import Database

    d = Database(cfg.db_path)
    d.bootstrap()
    return d


def _put_on(app, needle, token):
    line = SRC.splitlines()
    for i, ln in enumerate(line, 1):
        if needle in ln:
            app.st.row, app.st.col = i, ln.index(token)
            return
    raise AssertionError(needle)


def test_ctrl_t_refused_when_allow_import_is_off(cfg):
    app = _app(cfg)  # cfg.trust.allow_import defaults to False
    _put_on(app, "import pytest", "pytest")
    app._trust_under_cursor(TIER_IMPORT)
    assert "allow_import" in app.st.status
    assert "pytest" not in app._trusted


def test_persisted_import_trust_is_ignored_when_allow_import_off(cfg):
    from codecrawler.trust import TrustStore, sha256_file

    target = Path(cfg.data_dir) / "f.py"
    TrustStore(cfg.trust_path).record(
        target, sha256_file(target), "pytest", TIER_IMPORT
    )
    app = _app(cfg)
    assert "pytest" not in app._trusted  # not loaded — importing is disabled


def test_trust_hint_only_appears_on_an_untrusted_module(cfg):
    app = _app(cfg)
    _put_on(app, "import pytest", "pytest")
    hint = app._trust_hint(app._resolve_ns())
    assert "t:read-source pytest" in hint
    assert "Ctrl-t" not in hint  # allow_import is off

    _put_on(app, "print(math.pi", "pi")  # stdlib — already trusted
    assert app._trust_hint(app._resolve_ns()) == ""

    _put_on(app, "def main", "main")  # not a module at all
    assert app._trust_hint(app._resolve_ns()) == ""


def test_trust_hint_includes_ctrl_t_when_allowed(cfg):
    cfg = replace(cfg, trust=TrustConfig(allow_import=True))
    app = _app(cfg)
    _put_on(app, "import pytest", "pytest")
    hint = app._trust_hint(app._resolve_ns())
    assert "t:read-source pytest" in hint and "Ctrl-t:import pytest" in hint


def test_source_trust_still_works_with_allow_import_off(cfg, monkeypatch):
    app = _app(cfg)
    monkeypatch.setattr(app, "_confirm", lambda q: True)
    _put_on(app, "import pytest", "pytest")
    app._trust_under_cursor(TIER_SOURCE)
    assert app._trusted.get("pytest") == TIER_SOURCE
    assert "trusted pytest" in app.st.status
