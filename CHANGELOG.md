# Changelog

## v1.1.0 — 2026-08-29

Explanation depth and a concept library.

- **Verbosity levels** replace the short/full toggle. `Tab` / `Shift-Tab` cycle
  `0`–`3` (label only → one sentence → why + example + matched entry →
  + fundamentals). The starting level is `[display] verbosity` in the config and
  is shown in the status bar (`v0`–`v3`).
- **Concept library** (`seeds/concepts.json`, 20 language-neutral entries):
  reusable background explanations — *what a call is*, *arguments vs. parameters*,
  *blocks and indentation*, *truthiness*, *mutability*, *scope*, and more. A new
  `concept` table stores them (with an optional per-language override); the
  Python analyzer maps its tokens and lines to the shared slugs. At verbosity 3
  the full text shows in line mode; character mode shows a pointer. Missing
  concepts can be fetched with `?` and saved.
- **Character-mode cursor fix**: the cursor now visibly moves one character at a
  time — the reverse-video block is the single character under the cursor, with
  the surrounding token underlined — instead of jumping token to token.
- Explanation pane is now scrollable (`J` / `K`, with `▲`/`▼` indicators) so
  level-3 text fits.
- `?` prompts adapt to the current verbosity (terser at `0`, "assume no prior
  knowledge, define your terms" at `3`) and include the linked concept slugs.
- New: `codecrawler --list-concepts`. `--selftest` now reports concept coverage.
- Schema bumped to v2; existing databases migrate in place on next run.
- Tests: 57 cases (was 43).

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
