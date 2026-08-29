"""The curses application: layout, cursor navigation, and the ask/import/save flow."""

from __future__ import annotations

import curses
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..db import Database
from ..explain import CHAR, LINE, ExplanationEngine
from ..languages import Analyzer
from . import keys as keymod
from .panes import answer_body, explanation_body, scroll_to_show, wrap

EXPLAIN_HEIGHT = 11  # rows reserved for the explanation pane (incl. its border)


@dataclass
class _State:
    lines: list[str]
    row: int = 1  # 1-based
    col: int = 0  # 0-based
    mode: str = CHAR
    detail: bool = False
    scroll: int = 0
    status: str = ""
    pending: object = None  # ParsedAnswer awaiting save, or None


class App:
    def __init__(
        self,
        path: Path,
        source: str,
        analyzer: Analyzer,
        engine: ExplanationEngine,
        cfg: Config,
    ):
        self.path = path
        self.source = source
        self.analyzer = analyzer
        self.engine = engine
        self.cfg = cfg
        self.analysis = analyzer.analyze(source)
        lines = source.splitlines() or [""]
        self.st = _State(lines=lines)
        if not self.analysis.ok and self.analysis.error:
            self.st.status = f"note: {self.analysis.error}"

    # -- lifecycle ---------------------------------------------------

    def run(self) -> None:
        curses.wrapper(self._loop)

    def _loop(self, stdscr: "curses._CursesWindow") -> None:
        curses.curs_set(0)
        stdscr.keypad(True)
        self.stdscr = stdscr
        while True:
            self._clamp()
            self._render()
            key = stdscr.getch()
            action = keymod.resolve(key)
            if action == "quit":
                return
            if self.st.pending is not None:
                if self._handle_answer_key(action):
                    continue
            if action == "help":
                self._show_help()
                continue
            self._dispatch(action)

    # -- navigation ------------------------------------------------

    def _cur_line(self) -> str:
        return self.st.lines[self.st.row - 1] if self.st.lines else ""

    def _clamp(self) -> None:
        st = self.st
        st.row = max(1, min(st.row, len(st.lines)))
        line = self._cur_line()
        if st.mode == LINE:
            st.col = 0
        else:
            st.col = max(0, min(st.col, max(0, len(line) - 1)))

    def _dispatch(self, action: str | None) -> None:
        st = self.st
        if action == "move_left":
            self._move_horizontal(-1)
        elif action == "move_right":
            self._move_horizontal(1)
        elif action == "move_up":
            st.row -= 1
        elif action == "move_down":
            st.row += 1
        elif action == "next_token":
            self._jump_token(1)
        elif action == "prev_token":
            self._jump_token(-1)
        elif action == "line_start":
            st.col = 0
        elif action == "line_end":
            st.col = max(0, len(self._cur_line()) - 1)
        elif action == "top":
            st.row, st.col = 1, 0
        elif action == "bottom":
            st.row, st.col = len(st.lines), 0
        elif action == "page_up":
            st.row -= max(1, self._code_height() - 1)
        elif action == "page_down":
            st.row += max(1, self._code_height() - 1)
        elif action == "toggle_mode":
            st.mode = LINE if st.mode == CHAR else CHAR
            st.status = f"{st.mode} mode"
        elif action == "toggle_detail":
            st.detail = not st.detail
        elif action == "ask":
            self._ask()
        elif action == "import_answer":
            self._import_answer()

    def _move_horizontal(self, delta: int) -> None:
        st = self.st
        if st.mode == LINE:
            st.row += delta
            return
        st.col += delta
        line = self._cur_line()
        if st.col < 0:
            if st.row > 1:
                st.row -= 1
                st.col = max(0, len(self.st.lines[st.row - 1]) - 1)
            else:
                st.col = 0
        elif st.col >= len(line):
            if st.row < len(st.lines):
                st.row += 1
                st.col = 0
            else:
                st.col = max(0, len(line) - 1)

    def _jump_token(self, direction: int) -> None:
        toks = self.analysis.meaningful_tokens()
        if not toks:
            return
        pos = (self.st.row, self.st.col)
        if direction > 0:
            for t in toks:
                if t.start > pos:
                    self.st.row, self.st.col = t.start
                    return
            self.st.row, self.st.col = toks[-1].start
        else:
            prev = toks[0]
            for t in toks:
                if t.start >= pos:
                    break
                prev = t
            self.st.row, self.st.col = prev.start

    # -- ask / import / save -------------------------------------

    def _context(self):
        return self.engine.context(
            self.analysis,
            self.source,
            self.st.row,
            self.st.col,
            self.st.mode,
            context_lines=self.cfg.ai.context_lines,
        )

    def _ask(self) -> None:
        from ..ai import build_prompt
        from ..ai import bridge

        ctx = self._context()
        prompt = build_prompt(ctx)
        method = self.cfg.ai.method
        if method == "api":
            from ..ai import api

            ok, why = api.available()
            if ok:
                self.st.status = "asking Claude…"
                self._render()
                try:
                    raw = api.ask(self.cfg, prompt)
                    from ..ai import parse_answer

                    self.st.pending = parse_answer(raw)
                    self.st.status = "answer received — [s]ave [e]dit [d]iscard"
                    return
                except Exception as exc:  # fall through to bridge
                    self.st.status = f"API failed ({exc}); wrote bridge prompt instead"
            else:
                self.st.status = f"{why}; wrote bridge prompt instead"
        ask_path, copied = bridge.write_ask(self.cfg, prompt)
        tail = " (copied to clipboard)" if copied else ""
        self.st.status = (
            f"prompt -> {ask_path}{tail}. Paste reply into {self.cfg.answer_path}, press i"
        )

    def _import_answer(self) -> None:
        from ..ai import bridge, parse_answer

        try:
            raw = bridge.read_answer(self.cfg)
        except FileNotFoundError:
            self.st.status = f"no answer file at {self.cfg.answer_path}"
            return
        self.st.pending = parse_answer(raw)
        self.st.status = "answer loaded — [s]ave [e]dit [d]iscard"

    def _handle_answer_key(self, action: str | None) -> bool:
        parsed = self.st.pending
        if action == "discard":
            self.st.pending = None
            self.st.status = "discarded"
            return True
        if action == "save":
            self._save_pending(parsed)
            return True
        if action == "edit_save":
            edited = self._edit_text(self._answer_to_text(parsed))
            if edited is not None:
                from ..ai import parse_answer

                self.st.pending = parse_answer(edited)
                self._save_pending(self.st.pending)
            return True
        return False

    def _save_pending(self, parsed) -> None:
        ctx = self._context()
        if ctx.mode == LINE:
            self.engine.save_note(ctx, parsed.raw or parsed.short)
            self.st.status = "saved as a note"
        else:
            title = parsed.title or (ctx.token.string if ctx.token else "token")
            self.engine.save_entry(
                ctx, title=title, short=parsed.short, long=parsed.long, example=parsed.example
            )
            self.st.status = "saved to database"
        self.st.pending = None

    @staticmethod
    def _answer_to_text(parsed) -> str:
        return (
            f"TITLE: {parsed.title}\n"
            f"SHORT: {parsed.short}\n"
            f"LONG: {parsed.long}\n"
            f"EXAMPLE: {parsed.example}\n"
        )

    def _edit_text(self, initial: str) -> str | None:
        editor = os.environ.get("EDITOR", "nano")
        fd, name = tempfile.mkstemp(suffix=".md", prefix="codecrawler-")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(initial)
            curses.endwin()
            subprocess.call([editor, name])
            self.stdscr.clear()
            curses.doupdate()
            return Path(name).read_text(encoding="utf-8")
        except Exception as exc:
            self.st.status = f"editor failed: {exc}"
            return None
        finally:
            try:
                os.unlink(name)
            except OSError:
                pass

    def _show_help(self) -> None:
        self.stdscr.clear()
        for i, line in enumerate(keymod.HELP_LINES):
            if i < curses.LINES - 1:
                self._addstr(i, 2, line[: curses.COLS - 3])
        self._addstr(
            min(len(keymod.HELP_LINES) + 1, curses.LINES - 1), 2, "press any key…"
        )
        self.stdscr.getch()

    # -- rendering ----------------------------------------------

    def _code_height(self) -> int:
        return max(1, curses.LINES - EXPLAIN_HEIGHT - 2)

    def _addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
        if y < 0 or y >= curses.LINES or x >= curses.COLS:
            return
        try:
            self.stdscr.addstr(y, x, text[: max(0, curses.COLS - x - 1)], attr)
        except curses.error:
            pass

    def _render(self) -> None:
        self.stdscr.erase()
        st = self.st
        code_h = self._code_height()
        gutter = len(str(len(st.lines))) + 1

        st.scroll = scroll_to_show(st.row - 1, st.scroll, code_h, len(st.lines))

        # status line
        mode_tag = "LINE" if st.mode == LINE else "CHAR"
        head = f" {self.path}  —  line {st.row} col {st.col}  [{mode_tag}]"
        self._addstr(0, 0, head.ljust(curses.COLS - 1), curses.A_REVERSE)

        tok = self.analysis.token_at(st.row, st.col)

        # code pane
        for i in range(code_h):
            lineno = st.scroll + i + 1
            y = 1 + i
            if lineno > len(st.lines):
                break
            text = st.lines[lineno - 1]
            self._addstr(y, 0, f"{lineno:>{gutter - 1}} ", curses.A_DIM)
            self._addstr(y, gutter, text.expandtabs(4))
            if lineno == st.row:
                self._highlight(y, gutter, text, tok)

        sep_y = 1 + code_h
        self._addstr(sep_y, 0, "─" * (curses.COLS - 1), curses.A_DIM)

        # explanation pane
        width = curses.COLS - 4
        if st.pending is not None:
            body = answer_body(st.pending, width)
        else:
            ctx = self._context()
            explanation = self.engine.explain(ctx, self.source)
            body = explanation_body(explanation, st.detail, width)
        for i, line in enumerate(body):
            if i >= EXPLAIN_HEIGHT:
                break
            self._addstr(sep_y + 1 + i, 2, line)

        # help / status line
        hint = (
            "?:ask  i:import  s/e/d:save  Tab:detail  m:mode  w/b:token  H:help  q:quit"
        )
        bottom = curses.LINES - 1
        self._addstr(bottom, 0, hint[: curses.COLS - 1], curses.A_DIM)
        if st.status:
            msg = " " + st.status + " "
            self._addstr(bottom, max(0, curses.COLS - 1 - len(msg)), msg, curses.A_REVERSE)

        self.stdscr.noutrefresh()
        curses.doupdate()

    def _highlight(self, y: int, gutter: int, text: str, tok) -> None:
        expanded = text.expandtabs(4)
        if self.st.mode == LINE:
            self._addstr(y, gutter, expanded, curses.A_REVERSE)
            return
        if tok is not None and tok.start[0] == self.st.row:
            start_col = tok.start[1]
            end_col = tok.end[1] if tok.end[0] == self.st.row else len(text)
            seg = text[start_col:end_col].expandtabs(4) or " "
            x = gutter + len(text[:start_col].expandtabs(4))
            self._addstr(y, x, seg, curses.A_REVERSE)
        else:
            col = self.st.col
            ch = text[col] if col < len(text) else " "
            x = gutter + len(text[:col].expandtabs(4))
            self._addstr(y, x, ch or " ", curses.A_REVERSE)


def run(path: Path, source: str, analyzer: Analyzer, db: Database, cfg: Config) -> None:
    engine = ExplanationEngine(db, analyzer)
    App(path, source, analyzer, engine, cfg).run()
