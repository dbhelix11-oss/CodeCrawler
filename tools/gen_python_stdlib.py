#!/usr/bin/env python3
"""Regenerate ``codecrawler/seeds/python_stdlib.json``.

An offline, one-time developer task: import a curated set of standard-library
modules, list their public names, and record a one-line blurb from each name's
docstring. The result ships with CodeCrawler so the "siblings" list for
``math.pi`` and friends works with no import at run time (trust tier 2).

Run with the project's Python:  ``.venv/bin/python tools/gen_python_stdlib.py``
"""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

# Modules safe and common enough to catalogue. Keep this list conservative —
# anything not here still works via the `t` / Ctrl-t trust keys at run time.
MODULES = [
    "math", "cmath", "statistics", "random", "decimal", "fractions",
    "string", "textwrap", "re", "difflib",
    "os", "os.path", "sys", "io", "pathlib", "shutil", "glob", "tempfile",
    "json", "csv", "sqlite3", "pickle", "base64", "hashlib", "secrets",
    "itertools", "functools", "operator", "collections", "heapq", "bisect", "array",
    "datetime", "time", "calendar", "zoneinfo",
    "dataclasses", "enum", "typing", "abc", "contextlib", "copy", "weakref",
    "argparse", "subprocess", "threading", "asyncio", "queue", "socket",
    "logging", "traceback", "warnings", "pprint", "unittest",
]

OUT = Path(__file__).resolve().parent.parent / "codecrawler" / "seeds" / "python_stdlib.json"


def first_line(obj) -> str:
    doc = inspect.getdoc(obj) or ""
    line = doc.strip().splitlines()[0].strip() if doc.strip() else ""
    return line[:120]


def catalogue(mod_name: str) -> dict[str, str]:
    mod = importlib.import_module(mod_name)
    out: dict[str, str] = {}
    names = getattr(mod, "__all__", None) or [n for n in dir(mod) if not n.startswith("_")]
    for name in sorted(set(names)):
        if name.startswith("_"):
            continue
        try:
            out[name] = first_line(getattr(mod, name))
        except Exception:
            out[name] = ""
    return out


def main() -> None:
    data: dict[str, dict[str, str]] = {}
    for name in MODULES:
        try:
            data[name] = catalogue(name)
        except Exception as exc:  # a module missing on this build is not fatal
            print(f"  skip {name}: {exc}")
    OUT.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    total = sum(len(v) for v in data.values())
    print(f"wrote {OUT}  ({len(data)} modules, {total} names)")


if __name__ == "__main__":
    main()
