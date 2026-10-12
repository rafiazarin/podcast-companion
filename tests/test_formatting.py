"""Tests for screen and download formatting."""
import random
from pathlib import Path

from formatting import excerpt_html, to_markdown
from grounding import TranscriptIndex
from schemas import parse_study_pack

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = (ROOT / "samples" / "sample_transcript.txt").read_text(encoding="utf-8")
PACK = parse_study_pack((ROOT / "tests" / "fixtures" / "answer_gpt-oss-120b.json").read_text(encoding="utf-8"),
                        TranscriptIndex(SAMPLE), random.Random(3))


def test_excerpt_highlights_the_right_part_and_adds_ellipses():
    text = "one two three four five"
    out = excerpt_html(text, 4, 18, 8, 13)
    assert out == '<div class="transcript">…two <mark>three</mark> four…</div>'


def test_excerpt_never_starts_or_ends_mid_word():
    out = excerpt_html("alpha beta gamma delta epsilon", 2, 26, 11, 16)
    assert out == '<div class="transcript">…beta <mark>gamma</mark> delta…</div>'


def test_excerpt_escapes_html_in_the_transcript():
    out = excerpt_html("say <script>alert(1)</script> now", 0, 34, 4, 29)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_markdown_has_every_section_and_the_correct_answers():
    md = to_markdown(PACK, PACK.overview, ["A notice."])
    assert "## Overview" in md and "## Chapters" in md and "## Quiz" in md
    assert "9 of 9 quotes were found" in md
    assert "> A notice." in md
    for q in PACK.quiz:
        assert f"Answer: {'ABCD'[q.answer_index]}. {q.options[q.answer_index]}" in md


def test_markdown_uses_the_revised_overview_when_given():
    assert "My shorter version." in to_markdown(PACK, "My shorter version.", [])
