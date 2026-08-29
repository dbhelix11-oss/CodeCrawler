import curses

from codecrawler.ui import keys


def test_pageup_pagedown_scroll_the_explanation_not_the_code():
    assert keys.resolve(curses.KEY_NPAGE) == "scroll_expl_page_down"
    assert keys.resolve(curses.KEY_PPAGE) == "scroll_expl_page_up"


def test_g_is_goto_line():
    assert keys.resolve(ord("g")) == "goto_line"
    assert keys.resolve(ord("G")) == "bottom"


def test_no_code_paging_actions_remain():
    assert "page_up" not in keys.DEFAULT_BINDINGS
    assert "page_down" not in keys.DEFAULT_BINDINGS
    assert "top" not in keys.DEFAULT_BINDINGS


def test_jk_still_line_scroll_the_explanation():
    assert keys.resolve(ord("J")) == "scroll_expl_down"
    assert keys.resolve(ord("K")) == "scroll_expl_up"
