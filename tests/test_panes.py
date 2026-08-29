from codecrawler.db import Concept
from codecrawler.explain import Explanation
from codecrawler.ui.panes import explanation_body, scroll_to_show, wrap


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
