# CodeCrawler

Crawl a source file character-by-character or line-by-line in the terminal, with
a narrated explanation of whatever is under the cursor: what a `(` / `{` / `:` /
`->` **is**, what it does **in this exact spot**, and **why it is there**. The
goal is to learn to *read* code syntax fluently, and to build up a local database
of explanations so you eventually don't need to ask anyone.

Python is the first supported language. The database schema is multi-language from
the start.

## Install

```sh
python -m venv .venv
.venv/bin/pip install -e .          # core: stdlib only, no third-party deps
.venv/bin/pip install -e ".[ai]"    # optional: adds the direct Anthropic API path
```

## Use

```sh
codecrawler samples/hello.py
```

First run creates `~/.config/codecrawler/config.toml` and seeds the database at
`~/.local/share/codecrawler/codecrawler.db` from the bundled starter entries
(~140 for Python).

### Keys

| key | action |
| --- | --- |
| `h j k l` / arrows | move the cursor (char mode) or move by line (line mode) |
| `w` / `b` | jump to next / previous token |
| `0` / `$` | start / end of line |
| `g` / `G` | go to a line number (prompts) / jump to the last line |
| `m` | toggle **character** ⇄ **line** mode |
| `Tab` / `Shift-Tab` | cycle explanation depth `0`–`3` (see below) |
| `J` / `K` | scroll the explanation pane one line (`▲`/`▼` show more) |
| `PgDn` / `PgUp` | scroll the explanation pane one page |
| `t` / `Ctrl-t` | trust the module under the cursor — read its source / import it (see **Trust**) |
| `?` | ask Claude about what's under the cursor |
| `i` | import a pasted answer (bridge mode) |
| `s` / `e` / `d` | save / edit-then-save / discard a fetched answer |
| `H` | help  · `q` quit |

In **character mode** the reverse-video block is the single character under the
cursor; the underline marks the whole token it belongs to (the unit being
explained). The explanation comes from the database, with a fallback chain from
the most specific `lexeme + type + role` down to a generic entry. In **line
mode** the whole line is highlighted and the explanation is generated offline
from the parsed syntax tree.

The code pane is syntax-highlighted — keywords, strings, comments, numbers,
function calls, and the names in `def` / `class` headers each get a colour. Set
`[display] color = false` in the config to turn it off; it is skipped
automatically on terminals with no colour support.

### Verbosity (`Tab`)

`Tab` cycles a depth level, shown in the status bar as `v0`–`v3` and remembered
in the config (`[display] verbosity`):

| level | shows |
| --- | --- |
| `0` | just the label |
| `1` | one sentence |
| `2` | + why it's there + an example + which database entry matched |
| `3` | + linked **fundamentals** — in line mode the full concept text; in character mode a pointer listing them (switch to line mode to read) |

The fundamentals come from a small, mostly language-neutral **concept library**
(`seeds/concepts.json`, ~20 entries: *what a call is*, *arguments vs.
parameters*, *blocks and indentation*, *truthiness*, *mutability*, …). Each
language's analyzer links its tokens and lines to these shared slugs, so the same
concepts are reused when more languages are added. Missing concepts can be
fetched with `?` and saved like any other entry.

### Namespaces & trust

At depth `2` and above the explanation pane adds a **siblings line** — the other
names that sit beside the one under the cursor:

- `math.pi` → `math also defines: tau  e  inf  sqrt  …`
- `self.radius` inside a class → that class's other attributes and methods
- `c` where `c = Circle(2)` → `Circle`'s members

Names defined **in the file you're crawling** are resolved straight from the
parsed syntax tree — nothing is executed. **Standard-library** modules are
trusted automatically and read from bundled data.

A **third-party** module is different: to list what's inside it CodeCrawler has
to read files it didn't write, or import it. So third-party module names start
*untrusted* — dimmed in the code pane at any depth above `0`. Move the cursor
onto one and the status bar shows the trust keys for it:

| key | what it does |
| --- | --- |
| `t` | locate the module's own `.py` source, parse it, list the names — **no code runs** |
| `Ctrl-t` | `import` the module and inspect it — **this runs the module's top-level code**. Disabled unless `[trust] allow_import = true`; only needed for C-extension modules (`t` can't read those). |

Both ask for a `y` first. The choice is saved per file in
`<data_dir>/trust.json`, keyed by the file's path and a hash of its contents.
Reopening the file re-applies a `t` trust silently (unless the file changed
since), while a `Ctrl-t` trust always asks once more per session before it takes
effect. Turn the whole feature off with `[trust] enabled = false`.

### Asking Claude (`?`)

Set `[ai] method` in the config:

- `bridge` (default) — writes a ready-made prompt to
  `~/.local/share/codecrawler/ask.md` (and the clipboard if possible). Paste it
  into Claude Code, paste the reply into `answer.md`, press `i`. No API key.
- `api` — calls the Anthropic API directly (needs `pip install ".[ai]"` and
  either `ANTHROPIC_API_KEY` or an `ant auth login` profile). Model is
  `[ai] model` (default `claude-opus-5`; `claude-sonnet-5` is cheaper).

Either way you then get `[s] save / [e] edit / [d] discard`. Saved character-mode
answers become database entries (`source = ai`); saved line-mode answers become
free-form notes.

## Other commands

```sh
codecrawler --dump-db python          # print every entry for a language
codecrawler --list-concepts           # print the background-concept library
codecrawler --selftest samples/hello.py   # headless: token/role/concept coverage, line readings
codecrawler --lang python path/to/file    # force a language
codecrawler --ai api path/to/file         # override the AI method for one run
```

## Layout

```
codecrawler/
  cli.py            argument parsing, first-run setup
  config.py         ~/.config/codecrawler/config.toml
  db.py             SQLite schema, seeding, lookup resolution chain
  explain.py        engine: cursor context -> Explanation
  trust.py          per-file trust store for module inspection (trust.json)
  languages/        base.py (Analyzer ABC + Token), python_lang.py (tokenize + ast),
                    py_introspect.py (read-source / import a trusted module)
  ai/               prompt.py (shared), bridge.py (copy/paste), api.py (Anthropic SDK)
  ui/               curses app — all terminal code is confined here
  seeds/python.json         the starter token database
  seeds/concepts.json       the language-neutral concept library
  seeds/python_stdlib.json  bundled standard-library member lists
tests/              pytest suite
samples/hello.py    a file to crawl
```

## Running tests

```sh
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```
