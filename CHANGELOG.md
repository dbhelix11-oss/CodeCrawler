# Changelog

## v1.3.0 — 2026-08-29

Namespace resolution and per-file module trust.

- At depth 2+ the explanation pane now shows a **"siblings" line** — the other
  names that live beside the one under the cursor. `math.pi` lists `tau`, `e`,
  `sqrt`, …; `self.radius` inside a class lists that class's other attributes
  and methods; `c.area()` where `c = Circle(2)` lists `Circle`'s members.
- Names defined **in the file being crawled** are resolved with no execution
  (the parsed syntax tree only): classes, `self`, and locals bound to an
  in-file class.
- **Standard-library** modules are trusted automatically and served from
  bundled data (`seeds/python_stdlib.json`, ~2000 names) — no import.
- **Third-party modules start untrusted.** Above depth 0 their name is dimmed
  in the code pane, and the status bar offers the trust keys only while the
  cursor is on one. Press:
  - `t` — read its `.py` source and list the names (no code runs)
  - `Ctrl-t` — import it (this *runs* the module's top-level code). **Off by
    default** — enable with `[trust] allow_import = true`; only needed for
    C-extension modules, whose lists `t` cannot produce.
  Both ask `y`/`n` first. The decision is saved per file in
  `<data_dir>/trust.json` and keyed by the file's path + a hash of its
  contents.
- On reopening a file: source-trust (`t`) is re-applied silently unless the
  file changed since (then it reverts to untrusted); import-trust (`Ctrl-t`)
  always asks once more per session before it takes effect. If a trusted
  single-file module's own source changed, the re-confirm prompt says so.
- New config section `[trust]` (`enabled`, `stdlib`, `allow_import`).
- `tools/gen_python_stdlib.py` regenerates the bundled data.
- Tests: 93 cases (was 66).

## v1.2.0 — 2026-08-29

Syntax highlighting in the code pane. (Never tagged on its own; shipped as part
of the v1.3.0 release.)

- The code pane now colours tokens by kind: keywords, strings, comments,
  numbers, function calls, and the names in `def` / `class` headers (decorators
  too). The character-under-cursor block and the token underline still sit on
  top, and the underlined token keeps its colour.
- New `[display] color` config key (default `true`). Colour is skipped
  automatically when the terminal reports no colour support, so nothing breaks
  on a bare TTY.
- The token → colour mapping is a pure helper (`ui/panes.py`:
  `token_style` / `highlight_spans`), separate from the curses code, so other
  languages reuse it once they tag the same token types and roles.

## v1.1.1 — 2026-08-29

Navigation cleanup.

- `PgDn` / `PgUp` now scroll only the explanation pane (one page). They no
  longer move the cursor through the code.
- `g` opens a `go to line:` prompt (type a number, Enter jumps there, Esc
  cancels) — the way to move quickly through a large file now that PgUp/PgDn
  are explanation-only. `G` still jumps to the last line.
- Removed the page-jump-through-code binding and the `g`/`G` = top/bottom
  behaviour it replaced.

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
