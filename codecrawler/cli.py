"""Command-line entry point for CodeCrawler."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, config
from .db import Database
from .explain import CHAR, LINE, ExplanationEngine
from .languages import available as available_languages
from .languages import for_path, get


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="codecrawler",
        description="Crawl source code with a narrated explanation of every syntax element.",
    )
    p.add_argument("file", nargs="?", help="source file to open")
    p.add_argument("--lang", help=f"force a language ({', '.join(available_languages())})")
    p.add_argument("--config", help="path to a config.toml (default: ~/.config/codecrawler/config.toml)")
    p.add_argument("--ai", choices=["bridge", "api"], help="override the AI method for this run")
    p.add_argument("--dump-db", metavar="LANG", help="print every database entry for LANG and exit")
    p.add_argument("--list-concepts", action="store_true", help="print the background-concept library and exit")
    p.add_argument("--selftest", metavar="FILE", help="analyze FILE headlessly and print a summary (no TUI)")
    p.add_argument("--version", action="version", version=f"codecrawler {__version__}")
    return p


def _load(cfg_path: str | None):
    cfg_file = config.ensure_file(cfg_path)
    cfg = config.load(cfg_file)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(cfg.db_path)
    loaded = db.bootstrap()
    return cfg, db, loaded


def _pick_analyzer(path: Path, lang: str | None):
    analyzer = get(lang) if lang else for_path(path)
    if analyzer is None:
        langs = ", ".join(available_languages())
        raise SystemExit(
            f"No analyzer for {path.name}. Use --lang with one of: {langs}"
        )
    return analyzer


def _dump_db(db: Database, language: str) -> int:
    entries = db.all_entries(language)
    if not entries:
        print(f"(no entries for {language})")
        return 1
    for e in entries:
        role = f"/{e.role}" if e.role else ""
        print(f"{e.lexeme!r:12} [{e.token_type}{role}] ({e.source})")
        print(f"    {e.title}: {e.short}")
        if e.long:
            print(f"    {e.long}")
    print(f"\n{len(entries)} entries for {language}")
    return 0


def _list_concepts(db: Database) -> int:
    concepts = db.all_concepts()
    if not concepts:
        print("(no concepts)")
        return 1
    for c in concepts:
        scope = c.language or "all languages"
        print(f"{c.slug}  [{scope}] ({c.source})")
        print(f"    {c.title}")
        first = c.body.split("\n\n", 1)[0]
        print(f"    {first}")
        print()
    print(f"{len(concepts)} concepts")
    return 0


def _selftest(db: Database, path: Path, lang: str | None) -> int:
    analyzer = _pick_analyzer(path, lang)
    source = path.read_text(encoding="utf-8")
    analysis = analyzer.analyze(source)
    engine = ExplanationEngine(db, analyzer)
    print(f"file: {path}")
    print(f"analyzer: {analyzer.name}")
    print(f"tokens: {len(analysis.tokens)}  parsed_ok: {analysis.ok}  error: {analysis.error or '-'}")

    roled = [t for t in analysis.tokens if t.role]
    print(f"role-tagged tokens: {len(roled)}")
    misses = 0
    for tok in analysis.meaningful_tokens():
        hit = db.lookup(analyzer.name, tok.lexeme, tok.type, tok.role)
        if hit is None:
            misses += 1
    print(f"lookup misses over {len(analysis.meaningful_tokens())} tokens: {misses}")

    with_concepts = sum(1 for t in analysis.meaningful_tokens() if t.concepts)
    print(f"tokens linked to a concept: {with_concepts}  ·  concept library: {db.count_concepts()}")

    lines = source.splitlines()
    sample = list(range(1, min(len(lines), 12) + 1))
    print("\nline readings (with linked concepts):")
    for r in sample:
        if not lines[r - 1].strip():
            continue
        ctx = engine.context(analysis, source, r, 0, LINE)
        slugs = ", ".join(ctx.concepts) or "-"
        print(f"  L{r}: {engine.explain(ctx, source).short}")
        print(f"        concepts: {slugs}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except BrokenPipeError:  # e.g. `codecrawler --dump-db python | head`
        return 0


def _main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.dump_db:
        _cfg, db, _loaded = _load(args.config)
        return _dump_db(db, args.dump_db)

    if args.list_concepts:
        _cfg, db, _loaded = _load(args.config)
        return _list_concepts(db)

    if args.selftest:
        _cfg, db, _loaded = _load(args.config)
        return _selftest(db, Path(args.selftest), args.lang)

    if not args.file:
        _build_parser().print_help()
        return 2

    path = Path(args.file)
    if not path.is_file():
        raise SystemExit(f"not a file: {path}")

    cfg, db, loaded = _load(args.config)
    if args.ai:
        cfg = config.with_ai_method(cfg, args.ai)
    analyzer = _pick_analyzer(path, args.lang)
    source = path.read_text(encoding="utf-8")

    if loaded:
        summary = ", ".join(f"{k}:{v}" for k, v in loaded.items())
        print(f"seeded database ({summary}) at {cfg.db_path}")

    from .ui import run as run_ui

    try:
        run_ui(path, source, analyzer, db, cfg)
    except KeyboardInterrupt:
        pass
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
