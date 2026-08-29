# Changelog

## v1.0.0 — 2026-08-29

First public release. Adds `LICENSE` (MIT) and sets the package version to
`1.0.0`; the feature set below is unchanged from the initial build.

Initial CodeCrawler build.

- **Core engine** (`codecrawler/`, stdlib only): SQLite syntax database with a
  most-specific-to-generic lookup resolution chain (`db.py`); cursor-context
  explanation engine (`explain.py`).
- **Python analyzer** (`languages/python_lang.py`): `tokenize` token stream +
  `ast` role tagging that distinguishes `(` as call / def params / class bases /
  tuple / generator / grouping, `[` / `{` / `:` / `=` / `*` / `**` by context,
  f-string fields, decorators, comprehension clauses, and more; plus an offline
  template layer that reads a whole line as an English sentence.
- **Starter database** (`seeds/python.json`): ~140 hand-authored Python entries
  covering punctuation, operators, keywords, literal forms, and pseudo-tokens,
  each leading with *why the symbol is there*.
- **Ask flow** (`ai/`): a shared prompt builder feeding two paths — a keyless
  copy/paste "bridge" and a direct Anthropic API call (`[ai]` extra). Answers can
  be saved back into the database (`source = ai`) or as notes.
- **curses UI** (`ui/`): split-pane TUI — code pane with a movable cursor and
  token highlight, explanation pane, status/help lines; character ⇄ line mode;
  short/full detail toggle; `?` / `i` / `s` / `e` / `d` ask-and-save flow. All
  terminal code is confined to `ui/` to keep a future Textual port isolated.
- **CLI**: `codecrawler FILE`, `--dump-db`, `--selftest`, `--lang`, `--ai`.
- **Tests**: 43 pytest cases across db resolution, analyzer roles + line
  templates, engine behaviour, and the AI prompt/bridge round-trip.
