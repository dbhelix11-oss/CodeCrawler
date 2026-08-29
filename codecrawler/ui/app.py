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
from ..explain import CHAR, LINE, ExplanationEngine, SiblingList
from ..languages import Analyzer, py_introspect
from ..trust import TIER_IMPORT, TIER_SOURCE, TrustStore, sha256_file
from . import keys as keymod
from .panes import (
    STYLES,
    answer_body,
    explanation_body,
    highlight_spans,
    scroll_to_show,
    token_style,
    wrap,
)

EXPLAIN_HEIGHT = 11  # rows reserved for the explanation pane (incl. its border)


@dataclass
class _State:
    lines: list[str]
    row: int = 1  # 1-based
    col: int = 0  # 0-based
    mode: str = CHAR
    verbosity: int = 1  # 0..3
    scroll: int = 0  # code pane scroll (top line index)
    expl_scroll: int = 0  # explanation pane scroll
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
        self.st = _State(lines=lines, verbosity=cfg.display.verbosity)
        self._style_attr: dict[str, int] = {}  # style name -> curses attribute
        if not self.analysis.ok and self.analysis.error:
            self.st.status = f"note: {self.analysis.error}"

        # per-file trust for module inspection
        self.trust_store = TrustStore(cfg.trust_path)
        self.file_sha = sha256_file(path)
        self._trusted: dict[str, int] = {}  # module -> tier in effect
        self._session_ok: set[str] = set()  # tier-4 modules re-confirmed this session
        self._trust_stale = False
        self._load_trust()

    # -- lifecycle ---------------------------------------------------

    def run(self) -> None:
        curses.wrapper(self._loop)

    def _loop(self, stdscr: "curses._CursesWindow") -> None:
        curses.curs_set(0)
        stdscr.keypad(True)
        self.stdscr = stdscr
        self._init_colors()
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

    # -- colour --------------------------------------------------

    # style name -> terminal colour (foreground); anything absent stays default.
    _PALETTE = {
        "keyword": ("MAGENTA", True),
        "string": ("GREEN", False),
        "comment": ("BLUE", False),
        "number": ("CYAN", False),
        "call": ("CYAN", False),
        "definition": ("CYAN", True),
        "decorator": ("YELLOW", False),
    }

    def _init_colors(self) -> None:
        """Build ``self._style_attr``: a curses attribute per syntax style.

        Left empty (so rendering stays plain) when the config disables colour or
        the terminal cannot do it.
        """
        self._style_attr = {}
        if not self.cfg.display.color:
            return
        try:
            curses.start_color()  # harmless if curses.wrapper already did it
            if not curses.has_colors():
                return
            try:
                curses.use_default_colors()
                bg = -1
            except curses.error:
                bg = curses.COLOR_BLACK
            for i, name in enumerate(STYLES, start=1):
                spec = self._PALETTE.get(name)
                if spec is None:
                    continue
                color_name, bold = spec
                fg = getattr(curses, f"COLOR_{color_name}")
                curses.init_pair(i, fg, bg)
                attr = curses.color_pair(i)
                if bold:
                    attr |= curses.A_BOLD
                self._style_attr[name] = attr
        except curses.error:
            self._style_attr = {}

    def _tok_attr(self, tok) -> int:
        if tok is None:
            return 0
        if getattr(tok, "ref", "") and self._effective_tier(tok.ref) == 0:
            return curses.A_DIM
        return self._style_attr.get(token_style(tok.type, tok.role), 0)

    # -- trust (module inspection) ------------------------------

    def _is_stdlib(self, module: str) -> bool:
        fn = getattr(self.analyzer, "is_stdlib", None)
        return bool(fn(module)) if fn else False

    def _load_trust(self) -> None:
        if not self.cfg.trust.enabled:
            return
        ft = self.trust_store.for_file(self.path)
        if not ft.modules:
            return
        self._trust_stale = bool(ft.file_sha256) and ft.file_sha256 != self.file_sha
        for name, mt in ft.modules.items():
            if mt.tier == TIER_SOURCE and not self._trust_stale:
                self._trusted[name] = TIER_SOURCE
            elif mt.tier == TIER_IMPORT and self.cfg.trust.allow_import:
                self._trusted[name] = TIER_IMPORT  # needs a session re-confirm to take effect
        if self._trust_stale:
            self.st.status = (
                f"{self.path.name} changed since it was last trusted — re-press t / Ctrl-t to re-trust"
            )
        elif any(t == TIER_IMPORT for t in self._trusted.values()):
            self.st.status = "import-trusted modules here need Ctrl-t once to re-confirm this session"

    def _effective_tier(self, module: str) -> int:
        """Trust tier for ``module`` right now; 0 means not usable."""
        if not self.cfg.trust.enabled:
            return 0
        if self.cfg.trust.stdlib and self._is_stdlib(module):
            return 2
        tier = self._trusted.get(module, 0)
        if tier == TIER_IMPORT and module not in self._session_ok:
            return 0
        return tier

    def _module_refs(self) -> set[str]:
        return {t.ref for t in self.analysis.tokens if getattr(t, "ref", "")}

    def _dim_refs(self) -> set[str]:
        if self.st.verbosity < 1 or not self.cfg.trust.enabled:
            return set()
        return {m for m in self._module_refs() if self._effective_tier(m) == 0}

    def _resolve_ns(self):
        """The :class:`NamespaceRef` at the cursor, or ``None``."""
        if not self.cfg.trust.enabled or self.st.mode == LINE:
            return None
        try:
            return self.analyzer.resolve_namespace(self.source, self.st.row, self.st.col)
        except Exception:
            return None

    def _siblings_for(self, ref) -> "SiblingList | None":
        if ref is None:
            return None
        if ref.kind == "namespace":
            names = [m.name for m in ref.members]
            return SiblingList(
                owner=ref.owner, tier=1, trusted=True, names=names[:16], total=len(names)
            )
        mod = ref.module
        tier = self._effective_tier(mod)
        if tier == 0:
            hint = ""
            if self._trusted.get(mod) == TIER_IMPORT:
                hint = "trusted earlier by import — press Ctrl-t to re-confirm for this session"
            elif not self.cfg.trust.allow_import and "." not in mod:
                hint = "press t to read its source (importing it is off — [trust] allow_import)"
            return SiblingList(owner=mod, tier=0, trusted=False, names=[], total=0, hint=hint)
        names, total, hint = self._member_names(mod, tier)
        owner = f"module {mod}" if ref.from_import else mod
        return SiblingList(
            owner=owner, tier=tier, trusted=True, names=names, total=total, hint=hint
        )

    def _member_names(self, mod: str, tier: int) -> tuple[list[str], int, str]:
        cap, hint = 16, ""
        more = (
            "  press Ctrl-t to import it for the full list"
            if self.cfg.trust.allow_import
            else ""
        )
        if tier == 2:
            members = self.analyzer.module_members(mod) or []
            if not members:
                hint = "no bundled data for this module." + more
            names = [m.name for m in members]
        elif tier == TIER_SOURCE:
            members = py_introspect.read_source_members(mod) or []
            names = [m.name for m in members]
            if len(names) < 4:
                hint = "source read found little." + more
        else:  # TIER_IMPORT
            try:
                members = py_introspect.import_members(mod)
            except Exception as exc:
                return [], 0, f"import failed: {exc}"
            names = [m.name for m in members]
        return names[:cap], len(names), hint

    def _trust_under_cursor(self, tier: int) -> None:
        if not self.cfg.trust.enabled:
            self.st.status = "trust is disabled ([trust] enabled = false)"
            return
        try:
            ref = self.analyzer.resolve_namespace(self.source, self.st.row, self.st.col)
        except Exception:
            ref = None
        mod = ref.module if (ref and ref.kind == "module") else ""
        if not mod:
            self.st.status = "move the cursor onto a module name first"
            return
        if tier == TIER_IMPORT and not self.cfg.trust.allow_import:
            self.st.status = "importing modules is off — set [trust] allow_import = true to enable Ctrl-t"
            return
        if self._is_stdlib(mod) and self.cfg.trust.stdlib:
            self.st.status = f"{mod} is standard library — already trusted"
            return
        if tier == TIER_SOURCE and "." in mod:
            tail = "; use Ctrl-t" if self.cfg.trust.allow_import else ""
            self.st.status = f"can't source-read a dotted module ({mod}){tail}"
            return

        reconfirm = (
            tier == TIER_IMPORT
            and self._trusted.get(mod) == TIER_IMPORT
            and not self._trust_stale
        )
        if tier == TIER_SOURCE:
            q = f"Trust {mod}: read its .py source? No code runs. (y/n) "
        elif reconfirm:
            q = f"Re-confirm importing {mod} this session — RUNS its module code. (y/n) "
        else:
            q = f"Trust {mod}: IMPORT it? This RUNS {mod}'s module-level code. (y/n) "
            old = self.trust_store.for_file(self.path).modules.get(mod)
            srcf = py_introspect.module_source_file(mod)
            if old and old.module_sha256 and srcf:
                now = sha256_file(srcf)
                if now and now != old.module_sha256:
                    q = f"{mod}'s source CHANGED since last trusted. Import anyway (RUNS its code)? (y/n) "
        if not self._confirm(q):
            self.st.status = "not trusted"
            return

        if tier == TIER_SOURCE:
            if py_introspect.read_source_members(mod) is None:
                self.st.status = f"no source found for {mod} — try Ctrl-t"
                return
            module_sha = ""
        else:
            try:
                py_introspect.import_members(mod)
            except Exception as exc:
                self.st.status = f"import of {mod} failed: {exc}"
                return
            srcf = py_introspect.module_source_file(mod)
            module_sha = sha256_file(srcf) if srcf else ""

        self._trusted[mod] = tier
        if tier == TIER_IMPORT:
            self._session_ok.add(mod)
        self._trust_stale = False
        self.trust_store.record(self.path, self.file_sha, mod, tier, module_sha)
        kind = "source" if tier == TIER_SOURCE else "import"
        self.st.status = f"trusted {mod} ({kind}) — saved for {self.path.name}"

    def _confirm(self, question: str) -> bool:
        bottom = curses.LINES - 1
        self._render()
        self._addstr(bottom, 0, (" " + question).ljust(curses.COLS - 1), curses.A_REVERSE)
        self.stdscr.noutrefresh()
        curses.doupdate()
        k = self.stdscr.getch()
        return k in (ord("y"), ord("Y"))

    def _trust_hint(self, ref) -> str:
        """The trust keys to advertise in the status bar — only when the cursor
        is on an untrusted, inspectable module reference."""
        if ref is None or ref.kind != "module":
            return ""
        mod = ref.module
        if self._effective_tier(mod) != 0:
            return ""
        if self._is_stdlib(mod) and self.cfg.trust.stdlib:
            return ""
        parts = []
        if "." not in mod:
            parts.append(f"t:read-source {mod}")
        if self.cfg.trust.allow_import:
            parts.append(f"Ctrl-t:import {mod}")
        return "  ".join(parts)

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

    _MOVE_ACTIONS = {
        "move_left", "move_right", "move_up", "move_down", "next_token",
        "prev_token", "line_start", "line_end", "bottom", "goto_line",
    }

    def _dispatch(self, action: str | None) -> None:
        st = self.st
        if action in self._MOVE_ACTIONS:
            st.expl_scroll = 0
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
        elif action == "bottom":
            st.row, st.col = len(st.lines), 0
        elif action == "goto_line":
            self._goto_line()
        elif action == "scroll_expl_down":
            st.expl_scroll += 1
        elif action == "scroll_expl_up":
            st.expl_scroll = max(0, st.expl_scroll - 1)
        elif action == "scroll_expl_page_down":
            st.expl_scroll += max(1, EXPLAIN_HEIGHT - 1)
        elif action == "scroll_expl_page_up":
            st.expl_scroll = max(0, st.expl_scroll - max(1, EXPLAIN_HEIGHT - 1))
        elif action == "toggle_mode":
            st.mode = LINE if st.mode == CHAR else CHAR
            st.expl_scroll = 0
            st.status = f"{st.mode} mode"
        elif action == "cycle_verbosity":
            st.verbosity = (st.verbosity + 1) % 4
            st.expl_scroll = 0
            st.status = f"verbosity {st.verbosity}"
        elif action == "cycle_verbosity_back":
            st.verbosity = (st.verbosity - 1) % 4
            st.expl_scroll = 0
            st.status = f"verbosity {st.verbosity}"
        elif action == "trust_source":
            self._trust_under_cursor(TIER_SOURCE)
        elif action == "trust_import":
            self._trust_under_cursor(TIER_IMPORT)
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

    def _goto_line(self) -> None:
        raw = self._prompt(f"go to line (1-{len(self.st.lines)}): ")
        if not raw:
            return
        try:
            n = int(raw)
        except ValueError:
            self.st.status = f"not a line number: {raw!r}"
            return
        n = max(1, min(n, len(self.st.lines)))
        self.st.row, self.st.col = n, 0
        self.st.expl_scroll = 0
        self.st.status = f"line {n}"

    def _prompt(self, label: str) -> str | None:
        """Modal one-line text entry in the bottom bar. Enter confirms, Esc cancels."""
        buf = ""
        bottom = curses.LINES - 1
        while True:
            self._render()
            field = f" {label}{buf}█ "
            self._addstr(bottom, 0, field.ljust(curses.COLS - 1), curses.A_REVERSE)
            self.stdscr.noutrefresh()
            curses.doupdate()
            k = self.stdscr.getch()
            if k == 27:  # Esc
                return None
            if k in (10, 13, curses.KEY_ENTER):
                return buf
            if k in (curses.KEY_BACKSPACE, 127, 8):
                buf = buf[:-1]
            elif 0 <= k < 256 and chr(k).isdigit():
                buf += chr(k)

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
        prompt = build_prompt(ctx, self.st.verbosity)
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
        head = f" {self.path}  —  line {st.row} col {st.col}  [{mode_tag} v{st.verbosity}]"
        self._addstr(0, 0, head.ljust(curses.COLS - 1), curses.A_REVERSE)

        tok = self.analysis.token_at(st.row, st.col)
        ns_ref = self._resolve_ns()

        # code pane
        for i in range(code_h):
            lineno = st.scroll + i + 1
            y = 1 + i
            if lineno > len(st.lines):
                break
            text = st.lines[lineno - 1]
            self._addstr(y, 0, f"{lineno:>{gutter - 1}} ", curses.A_DIM)
            self._draw_code_line(y, gutter, text, lineno)
            if lineno == st.row:
                self._highlight(y, gutter, text, tok)

        sep_y = 1 + code_h
        self._addstr(sep_y, 0, "─" * (curses.COLS - 1), curses.A_DIM)

        # explanation pane
        width = curses.COLS - 4
        pane_h = EXPLAIN_HEIGHT
        if st.pending is not None:
            body = answer_body(st.pending, width)
        else:
            ctx = self._context()
            explanation = self.engine.explain(ctx, self.source)
            explanation.siblings = self._siblings_for(ns_ref)
            body = explanation_body(explanation, st.verbosity, ctx.mode, width)

        max_scroll = max(0, len(body) - pane_h)
        st.expl_scroll = max(0, min(st.expl_scroll, max_scroll))
        window = body[st.expl_scroll : st.expl_scroll + pane_h]
        for i, line in enumerate(window):
            self._addstr(sep_y + 1 + i, 2, line)
        if st.expl_scroll > 0:
            self._addstr(sep_y + 1, curses.COLS - 3, "▲", curses.A_DIM)
        if st.expl_scroll < max_scroll:
            self._addstr(sep_y + pane_h, curses.COLS - 3, "▼", curses.A_DIM)

        # help / status line
        trust_hint = self._trust_hint(ns_ref)
        hint = "?:ask g:goto Tab:depth J/K:scroll m:mode w/b:token s/e/d:save H:help q:quit"
        if trust_hint:
            hint = trust_hint + "   " + hint
        bottom = curses.LINES - 1
        self._addstr(bottom, 0, hint[: curses.COLS - 1], curses.A_DIM)
        if st.status:
            msg = " " + st.status + " "
            self._addstr(bottom, max(0, curses.COLS - 1 - len(msg)), msg, curses.A_REVERSE)

        self.stdscr.noutrefresh()
        curses.doupdate()

    def _draw_code_line(self, y: int, gutter: int, text: str, lineno: int) -> None:
        """Draw one code line: syntax colour where available, plus a dim overlay
        on references to modules that are not trusted yet (above verbosity 0)."""
        expanded = text.expandtabs(4)
        self._addstr(y, gutter, expanded)  # plain base pass: covers whitespace/gaps
        dim = self._dim_refs()
        if not self._style_attr and not dim:
            return
        for c0, c1, style in highlight_spans(
            self.analysis.tokens, lineno, len(text), dim_refs=dim
        ):
            attr = curses.A_DIM if style == "untrusted" else self._style_attr.get(style, 0)
            if not attr:
                continue
            x = gutter + len(text[:c0].expandtabs(4))
            self._addstr(y, x, text[c0:c1].expandtabs(4), attr)

    def _highlight(self, y: int, gutter: int, text: str, tok) -> None:
        """Line mode: reverse the whole line. Char mode: underline the token the
        cursor is in (so you see the unit being explained) and reverse the one
        character under the cursor (so you see it crawl)."""
        expanded = text.expandtabs(4)
        if self.st.mode == LINE:
            self._addstr(y, gutter, expanded, curses.A_REVERSE)
            return
        if tok is not None and tok.start[0] == self.st.row:
            start_col = tok.start[1]
            end_col = tok.end[1] if tok.end[0] == self.st.row else len(text)
            seg = text[start_col:end_col].expandtabs(4) or " "
            x = gutter + len(text[:start_col].expandtabs(4))
            self._addstr(y, x, seg, curses.A_UNDERLINE | self._tok_attr(tok))
        col = self.st.col
        ch = text[col] if col < len(text) else " "
        xc = gutter + len(text[:col].expandtabs(4))
        self._addstr(y, xc, ch or " ", curses.A_REVERSE)


def run(path: Path, source: str, analyzer: Analyzer, db: Database, cfg: Config) -> None:
    engine = ExplanationEngine(db, analyzer)
    App(path, source, analyzer, engine, cfg).run()
