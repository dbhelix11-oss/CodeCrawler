"""Key bindings. Values are the characters or curses key names bound to each
action; :func:`resolve` turns a pressed key into an action name.
"""

from __future__ import annotations

import curses

# action -> list of keys. Keys are either single characters or curses.KEY_* ints.
DEFAULT_BINDINGS: dict[str, list] = {
    "move_left": ["h", curses.KEY_LEFT],
    "move_right": ["l", curses.KEY_RIGHT],
    "move_up": ["k", curses.KEY_UP],
    "move_down": ["j", curses.KEY_DOWN],
    "prev_token": ["b"],
    "next_token": ["w"],
    "line_start": ["0", curses.KEY_HOME],
    "line_end": ["$", curses.KEY_END],
    "goto_line": ["g"],
    "bottom": ["G"],
    "scroll_expl_down": ["J"],
    "scroll_expl_up": ["K"],
    "scroll_expl_page_down": [curses.KEY_NPAGE],
    "scroll_expl_page_up": [curses.KEY_PPAGE],
    "toggle_mode": ["m"],
    "cycle_verbosity": ["\t"],
    "cycle_verbosity_back": [curses.KEY_BTAB],
    "trust_source": ["t"],  # trust the module under the cursor — read its source
    "trust_import": [20],  # Ctrl-t — trust it by importing (runs its code)
    "ask": ["?"],
    "import_answer": ["i"],
    "save": ["s"],
    "edit_save": ["e"],
    "discard": ["d", 27],  # 'd' or ESC
    "help": ["H"],
    "quit": ["q"],
}


def _norm(key: int) -> object:
    if 0 <= key < 256:
        return chr(key)
    return key


def resolve(key: int, bindings: dict[str, list] | None = None) -> str | None:
    bindings = bindings or DEFAULT_BINDINGS
    k = _norm(key)
    for action, keys in bindings.items():
        if key in keys or k in keys:
            return action
    return None


HELP_LINES = [
    "CodeCrawler keys",
    "",
    "  h/j/k/l or arrows   move the cursor (char mode) / move by line (line mode)",
    "  w / b               jump to next / previous token",
    "  0 / $               start / end of line",
    "  g                   go to a line number (prompts)        G   last line",
    "  m                   toggle character  <->  line mode",
    "  Tab / Shift-Tab     cycle explanation depth 0-3 (0 label .. 3 fundamentals)",
    "  J / K               scroll the explanation pane one line",
    "  PgDn / PgUp         scroll the explanation pane one page",
    "  t                   trust the module under the cursor: read its source (no code runs)",
    "  Ctrl-t              trust it by importing it — runs its code ([trust] allow_import)",
    "  ?                   ask Claude about what is under the cursor",
    "  i                   import a pasted answer (bridge mode)",
    "  s / e / d           save / edit-then-save / discard a fetched answer",
    "  H                   this help        q   quit",
]
