"""Registry mapping language names and file extensions to analyzers."""

from __future__ import annotations

from pathlib import Path

from .base import Analysis, Analyzer, Member, NamespaceRef, Token
from .python_lang import PythonAnalyzer

_ANALYZERS: list[Analyzer] = [PythonAnalyzer()]

__all__ = [
    "Analysis", "Analyzer", "Member", "NamespaceRef", "Token",
    "get", "for_path", "available",
]


def available() -> list[str]:
    return [a.name for a in _ANALYZERS]


def get(name: str) -> Analyzer | None:
    for a in _ANALYZERS:
        if a.name == name:
            return a
    return None


def for_path(path: str | Path) -> Analyzer | None:
    ext = Path(path).suffix.lower()
    for a in _ANALYZERS:
        if ext in a.extensions:
            return a
    return None
