"""Bridge mode: hand the prompt off to Claude Code (or any Claude chat) via a
file, and read the pasted reply back from another file. No API key needed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..config import Config
from .prompt import AskPrompt

_HEADER = (
    "# CodeCrawler — question for Claude\n"
    "# Paste everything below into Claude Code, then paste the reply into:\n"
    "#   {answer}\n"
    "# and press the import key in CodeCrawler.\n"
    "# ----------------------------------------------------------------------\n\n"
)


def clip_copy(text: str) -> bool:
    """Best-effort copy to the system clipboard; return True on success."""
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["pbcopy"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(
                    cmd,
                    input=text.encode(),
                    check=True,
                    timeout=5,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except Exception:
                continue
    return False


def write_ask(cfg: Config, prompt: AskPrompt) -> tuple[Path, bool]:
    """Write the prompt to ``ask.md``; return its path and whether it was copied."""
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    body = _HEADER.format(answer=cfg.answer_path) + prompt.full_text
    cfg.ask_path.write_text(body, encoding="utf-8")
    copied = clip_copy(prompt.full_text)
    return cfg.ask_path, copied


def read_answer(cfg: Config) -> str:
    """Return the text of ``answer.md``; raise FileNotFoundError if it is missing."""
    if not cfg.answer_path.is_file():
        raise FileNotFoundError(cfg.answer_path)
    return cfg.answer_path.read_text(encoding="utf-8")


def clear_answer(cfg: Config) -> None:
    try:
        cfg.answer_path.unlink()
    except FileNotFoundError:
        pass
