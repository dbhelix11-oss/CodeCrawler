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
| `0` / `$`, `g` / `G` | line start/end, file top/bottom |
| `m` | toggle **character** ⇄ **line** mode |
| `Tab` | toggle short / full explanation |
| `?` | ask Claude about what's under the cursor |
| `i` | import a pasted answer (bridge mode) |
| `s` / `e` / `d` | save / edit-then-save / discard a fetched answer |
| `H` | help  · `q` quit |

In **character mode** the explanation comes from the database (with a fallback
chain from the most specific `lexeme + type + role` down to a generic entry). In
**line mode** it is generated offline from the parsed syntax tree.

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
codecrawler --selftest samples/hello.py   # headless: token count, role coverage, line readings
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
  languages/        base.py (Analyzer ABC + Token) and python_lang.py (tokenize + ast)
  ai/               prompt.py (shared), bridge.py (copy/paste), api.py (Anthropic SDK)
  ui/               curses app — all terminal code is confined here
  seeds/python.json the starter database
tests/              pytest suite
samples/hello.py    a file to crawl
```

## Running tests

```sh
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```
