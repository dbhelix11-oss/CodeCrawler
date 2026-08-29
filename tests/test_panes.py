from codecrawler.db import Concept
from codecrawler.explain import Explanation, SiblingList
from codecrawler.ui.panes import (
    explanation_body,
    highlight_spans,
    scroll_to_show,
    token_style,
    wrap,
)


def _expl(**kw):
    base = dict(
        mode="char",
        found=True,
        title="Call parentheses",
        short="Runs the callable before it.",
        long="The parentheses are what execute the function.",
        example="print(x)",
        source="seed",
        matched=("(", "OP", "call"),
        subject="`(` [OP/call]",
        concept_slugs=["function-call"],
        concepts=[Concept(slug="function-call", title="What a call is", body="A function has two parts.")],
    )
    base.update(kw)
    return Explanation(**base)


def test_verbosity_0_is_header_only():
    body = explanation_body(_expl(), verbosity=0, mode="char", width=60)
    assert all("Runs the callable" not in ln for ln in body)


def test_verbosity_1_shows_short_not_long():
    body = "\n".join(explanation_body(_expl(), verbosity=1, mode="char", width=60))
    assert "Runs the callable" in body
    assert "what execute the function" not in body


def test_verbosity_2_shows_long_and_example():
    body = "\n".join(explanation_body(_expl(), verbosity=2, mode="char", width=60))
    assert "what execute the function" in body
    assert "print(x)" in body


def test_verbosity_3_char_mode_points_at_concepts():
    body = "\n".join(explanation_body(_expl(), verbosity=3, mode="char", width=70))
    assert "Fundamentals: function-call" in body
    assert "A function has two parts." not in body  # full text only in line mode


def test_verbosity_3_line_mode_shows_concept_body():
    body = "\n".join(explanation_body(_expl(mode="line"), verbosity=3, mode="line", width=70))
    assert "What a call is" in body
    assert "A function has two parts." in body


def test_verbosity_3_line_mode_flags_missing_concepts():
    e = _expl(mode="line", concept_slugs=["function-call", "not-written-yet"])
    body = "\n".join(explanation_body(e, verbosity=3, mode="line", width=70))
    assert "not-written-yet" in body
    assert "press ?" in body


def test_scroll_to_show_clamps():
    assert scroll_to_show(0, 5, 10, 100) == 0
    assert scroll_to_show(50, 0, 10, 100) == 41
    assert scroll_to_show(99, 0, 10, 100) == 90


# -- syntax highlighting -------------------------------------------------


def test_token_style_by_type():
    assert token_style("KEYWORD") == "keyword"
    assert token_style("STRING") == "string"
    assert token_style("COMMENT") == "comment"
    assert token_style("NUMBER") == "number"
    assert token_style("OP") == "operator"
    assert token_style("NAME") == "name"
    assert token_style("NEWLINE") == "name"  # unknown -> default


def test_token_style_role_wins_for_names():
    assert token_style("NAME", "definition") == "definition"
    assert token_style("NAME", "call") == "call"
    assert token_style("NAME", "attribute") == "name"  # role we don't colour
    assert token_style("OP", "call") == "operator"  # call colour is names-only
    assert token_style("OP", "decorator") == "decorator"


def test_highlight_spans_marks_each_kind(analyzer):
    src = "x = 1  # note\n"
    spans = highlight_spans(analyzer.analyze(src).tokens, 1, len(src.splitlines()[0]))
    styled = {style: (c0, c1) for c0, c1, style in spans}
    assert "number" in styled and src[slice(*styled["number"])] == "1"
    assert "comment" in styled and src[slice(*styled["comment"])].startswith("#")
    assert "operator" in styled and src[slice(*styled["operator"])] == "="


def test_highlight_spans_keyword_and_call(analyzer):
    src = "def greet():\n    print(1)\n"
    line2 = src.splitlines()[1]
    spans1 = highlight_spans(analyzer.analyze(src).tokens, 1, len(src.splitlines()[0]))
    assert any(style == "keyword" for _, _, style in spans1)
    assert any(style == "definition" for _, _, style in spans1)
    spans2 = highlight_spans(analyzer.analyze(src).tokens, 2, len(line2))
    assert any(style == "call" and line2[c0:c1] == "print" for c0, c1, style in spans2)


def test_highlight_spans_slices_a_multiline_string(analyzer):
    src = 's = """\nmiddle\n"""\n'
    spans = highlight_spans(analyzer.analyze(src).tokens, 2, len("middle"))
    assert spans == [(0, 6, "string")]


def test_highlight_spans_dims_untrusted_module_refs(analyzer):
    src = "import numpy as np\nnp.array([1])\n"
    toks = analyzer.analyze(src).tokens
    plain = highlight_spans(toks, 2, len("np.array([1])"))
    dimmed = highlight_spans(toks, 2, len("np.array([1])"), dim_refs={"numpy"})
    assert not any(s == "untrusted" for *_, s in plain)
    assert any(s == "untrusted" for *_, s in dimmed)


# -- siblings / namespace panel ---------------------------------------


def test_siblings_trusted_lists_names_at_v2():
    sib = SiblingList(owner="math", tier=2, trusted=True,
                      names=["pi", "tau", "e"], total=40)
    body = "\n".join(explanation_body(_expl(siblings=sib), verbosity=2, mode="char", width=70))
    assert "math also defines" in body
    assert "pi  tau  e" in body
    assert "+37 more" in body


def test_siblings_hidden_at_v1():
    sib = SiblingList(owner="math", tier=2, trusted=True, names=["pi"], total=1)
    body = "\n".join(explanation_body(_expl(siblings=sib), verbosity=1, mode="char", width=70))
    assert "math also defines" not in body


def test_siblings_untrusted_shows_trust_keys():
    sib = SiblingList(owner="numpy", tier=0, trusted=False)
    body = "\n".join(explanation_body(_expl(siblings=sib), verbosity=2, mode="char", width=70))
    assert "not trusted" in body
    assert "press t" in body and "Ctrl-t" in body


def test_siblings_reconfirm_hint_shown_for_untrusted_with_hint():
    sib = SiblingList(owner="numpy", tier=0, trusted=False,
                      hint="press Ctrl-t to re-confirm for this session")
    body = "\n".join(explanation_body(_expl(siblings=sib), verbosity=2, mode="char", width=70))
    assert "re-confirm" in body
