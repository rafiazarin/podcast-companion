"""Tests for the quote checker. They run without any API key or internet."""
from grounding import TranscriptIndex

TEXT = (
    "NADIA: Let's start with a confession. Before an exam, I reread my notes three or four times.\n\n"
    "ARIF: It’s the most common strategy, and it feels productive, but it’s one of the weakest.\n"
    "ARIF: Most students cram, which means doing all their studying in one long session.\n"
    "NADIA: Interleaving. I have to admit I'd never heard the word before.\n"
    "ARIF: Interleaving means mixing different types of problems in one session.\n"
    "NADIA: So, to repeat: interleaving means mixing different types of problems in one session."
)
index = TranscriptIndex(TEXT)


def test_exact_quote_is_found_and_points_at_the_real_text():
    quote = "Before an exam, I reread my notes three or four times."
    check = index.find(quote)
    assert check.verified
    assert TEXT[check.start:check.end] == "Before an exam, I reread my notes three or four times"


def test_capitals_quote_marks_dashes_and_spaces_are_ignored():
    quote = 'IT\'S the most   common strategy — and it feels productive, but it\'s one of the weakest'
    assert index.find(quote).verified


def test_short_quote_is_rejected_even_though_it_appears():
    check = index.find("Interleaving.")
    assert not check.verified
    assert "too short" in check.reason


def test_invented_quote_is_rejected():
    check = index.find("Rereading is the best way to prepare for any exam.")
    assert not check.verified
    assert "not found" in check.reason


def test_part_of_a_word_does_not_count():
    # The transcript says "studying". "study" is only the start of that word, so it must not match.
    assert not index.find("Most students cram, which means doing all their study").verified


def test_shortened_quote_with_ellipsis_is_rejected():
    assert not index.find("Most students cram ... in one long session").verified


def test_empty_quote_is_rejected():
    check = index.find("   ")
    assert not check.verified
    assert "empty" in check.reason


def test_chapters_are_found_in_order_even_when_a_phrase_repeats():
    starts = [
        "Let's start with a confession. Before an exam",
        "Most students cram, which means doing all their studying",
        "interleaving means mixing different types of problems in one session",
    ]
    checks = index.find_in_order(starts)
    assert all(c.verified for c in checks)
    assert checks[0].start < checks[1].start < checks[2].start


def test_chapter_out_of_order_is_flagged():
    starts = [
        "Most students cram, which means doing all their studying",
        "Let's start with a confession. Before an exam",
    ]
    checks = index.find_in_order(starts)
    assert checks[0].verified
    assert not checks[1].verified
    assert "order" in checks[1].reason


def test_bangla_text_works():
    bangla = "আজকের পর্বে আমরা পরীক্ষার আগে পড়ার সঠিক পদ্ধতি নিয়ে কথা বলব।"
    check = TranscriptIndex(bangla).find("আমরা পরীক্ষার আগে পড়ার সঠিক পদ্ধতি")
    assert check.verified
