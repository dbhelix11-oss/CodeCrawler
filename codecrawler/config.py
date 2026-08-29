"""Load and save CodeCrawler configuration.

Config lives at ``~/.config/codecrawler/config.toml`` (overridable with
``--config``). Reading uses the stdlib :mod:`tomllib`; writing uses a tiny
hand-rolled serializer so the base install needs no third-party TOML writer.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "codecrawler" / "config.toml"

# Kept in sync with the documented default file written on first run.
_DEFAULTS: dict[str, dict[str, object]] = {
    "general": {
        "data_dir": "~/.local/share/codecrawler",
        "default_language": "python",
    },
    "ai": {
        "method": "bridge",  # "bridge" | "api"
        "model": "claude-opus-5",  # api mode only; "claude-sonnet-5" is cheaper
        "max_tokens": 1500,
        "context_lines": 3,
    },
    "display": {
        "verbosity": 1,  # 0 label only · 1 one sentence · 2 + why/example · 3 + fundamentals
    },
}

VERBOSITY_MIN = 0
VERBOSITY_MAX = 3

_TEMPLATE = """\
# CodeCrawler configuration.

[general]
# Where the syntax database and the bridge-mode ask/answer files are kept.
data_dir = "~/.local/share/codecrawler"
# Language assumed when a file's extension is unknown.
default_language = "python"

[ai]
# How the "?" key gets an explanation from Claude:
#   "bridge" — write a prompt file to paste into Claude Code, paste the reply back.
#   "api"    — call the Anthropic API directly (needs `pip install "codecrawler[ai]"`
#              and credentials: ANTHROPIC_API_KEY or an `ant auth login` profile).
method = "bridge"
# Used only when method = "api". "claude-sonnet-5" is the cheaper option.
model = "claude-opus-5"
max_tokens = 1500
# Lines of surrounding code sent as context when asking.
context_lines = 3

[display]
# Starting explanation depth, cycled at runtime with Tab:
#   0  just the label
#   1  one sentence
#   2  sentence + why it is there + an example
#   3  everything above + linked language fundamentals (full text in line mode)
verbosity = 1
"""


@dataclass(frozen=True)
class GeneralConfig:
    data_dir: Path
    default_language: str


@dataclass(frozen=True)
class AIConfig:
    method: str
    model: str
    max_tokens: int
    context_lines: int


@dataclass(frozen=True)
class DisplayConfig:
    verbosity: int


@dataclass(frozen=True)
class Config:
    general: GeneralConfig
    ai: AIConfig
    display: DisplayConfig
    path: Path = field(default=DEFAULT_CONFIG_PATH)

    @property
    def data_dir(self) -> Path:
        return self.general.data_dir

    @property
    def db_path(self) -> Path:
        return self.general.data_dir / "codecrawler.db"

    @property
    def ask_path(self) -> Path:
        return self.general.data_dir / "ask.md"

    @property
    def answer_path(self) -> Path:
        return self.general.data_dir / "answer.md"


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


def _merge(base: dict, override: dict) -> dict:
    out = {k: dict(v) for k, v in base.items()}
    for section, values in override.items():
        if not isinstance(values, dict):
            continue
        out.setdefault(section, {}).update(values)
    return out


def load(path: Path | str | None = None) -> Config:
    """Read config from ``path`` (or the default), filling in any missing keys."""
    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    raw: dict = {}
    if cfg_path.is_file():
        with cfg_path.open("rb") as fh:
            raw = tomllib.load(fh)
    merged = _merge(_DEFAULTS, raw)

    general = GeneralConfig(
        data_dir=_expand(str(merged["general"]["data_dir"])),
        default_language=str(merged["general"]["default_language"]),
    )
    ai = AIConfig(
        method=str(merged["ai"]["method"]),
        model=str(merged["ai"]["model"]),
        max_tokens=int(merged["ai"]["max_tokens"]),
        context_lines=int(merged["ai"]["context_lines"]),
    )
    verbosity = int(merged["display"]["verbosity"])
    verbosity = max(VERBOSITY_MIN, min(VERBOSITY_MAX, verbosity))
    display = DisplayConfig(verbosity=verbosity)
    return Config(general=general, ai=ai, display=display, path=cfg_path)


def ensure_file(path: Path | str | None = None) -> Path:
    """Create the config file with default contents if it does not exist yet."""
    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(_TEMPLATE, encoding="utf-8")
    return cfg_path


def with_ai_method(cfg: Config, method: str) -> Config:
    """Return a copy of ``cfg`` with a different AI method (used by tests/CLI)."""
    return replace(cfg, ai=replace(cfg.ai, method=method))
