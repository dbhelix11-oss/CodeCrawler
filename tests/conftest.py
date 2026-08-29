import pathlib

import pytest

from codecrawler.config import AIConfig, Config, DisplayConfig, GeneralConfig
from codecrawler.db import Database
from codecrawler.explain import ExplanationEngine
from codecrawler.languages import get

SAMPLE = pathlib.Path(__file__).resolve().parents[1] / "samples" / "hello.py"


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "codecrawler.db")
    database.bootstrap()
    yield database
    database.close()


@pytest.fixture
def analyzer():
    return get("python")


@pytest.fixture
def engine(db, analyzer):
    return ExplanationEngine(db, analyzer)


@pytest.fixture
def sample_source():
    return SAMPLE.read_text(encoding="utf-8")


@pytest.fixture
def cfg(tmp_path):
    return Config(
        general=GeneralConfig(data_dir=tmp_path, default_language="python"),
        ai=AIConfig(method="bridge", model="claude-opus-5", max_tokens=1500, context_lines=3),
        display=DisplayConfig(verbosity=1),
        path=tmp_path / "config.toml",
    )
