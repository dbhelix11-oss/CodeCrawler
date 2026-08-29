"""Terminal UI for CodeCrawler.

All curses-specific code lives in this package so a future port to another
toolkit only has to replace ``ui/``; everything under ``codecrawler/`` outside
here is UI-agnostic.
"""

from .app import run

__all__ = ["run"]
