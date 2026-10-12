"""Tests for turning the AI's answer into a checked study pack. Two use real model answers."""
import json
import random
from pathlib import Path

import pytest

from grounding import TranscriptIndex
from schemas import BadOutput, parse_overview, parse_study_pack

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = (ROOT / "samples" / "sample_transcript.txt").read_text(encoding="utf-8")
INDEX = TranscriptIndex(SAMPLE)
FIXTURES = ROOT / "tests" / "fixtures"


def real_answer(model):
    return (FIXTURES / f"answer_{model}.json").read_text(encoding="utf-8")


def good_question(**changes):
    q = {"question": "What does active recall mean?",
         "options": ["Rereading notes", "Pulling information out of your own head", "Highlighting", "Sleeping"],
         "answer_index": 1,
         "explanation": "Arif defines it as retrieving from memory.",
         "evidence_quote": "That means closing the book and trying to pull the information out of your own head."}
    q.update(changes)
    return q


def pack(quiz=None, chapters=None):
    return json.dumps({
        "overview": "An episode about study techniques.",
        "chapters": chapters or [
            {"title": "Rereading", "summary": "Why rereading fails.",
             "start_quote": "It's the most common strategy, and it feels productive, but it's one of the weakest."},
            {"title": "Spacing", "summary": "Spread reviews out.",
             "start_quote": "Most students cram, which means doing all their studying in one long session"},
        ],
        "quiz": quiz if quiz is not None else [good_question(), good_question(), good_question()],
    })


def test_real_120b_answer_passes_with_every_quote_verified():
    result = parse_study_pack(real_answer("gpt-oss-120b"), INDEX, random.Random(1))
    assert result.quotes_verified == result.quotes_total == 9
    assert result.dropped_questions == 0


def test_real_20b_answer_has_its_one_word_chapter_quotes_flagged():
    result = parse_study_pack(real_answer("gpt-oss-20b"), INDEX, random.Random(1))
    flagged = [c.start_quote for c in result.chapters if not c.check.verified]
    assert "Interleaving." in flagged and "Highlighting." in flagged
    assert all(q.check.verified for q in result.quiz)


def test_shuffling_keeps_the_right_answer_and_moves_its_position():
    positions = set()
    for seed in range(20):
        q = parse_study_pack(pack(), INDEX, random.Random(seed)).quiz[0]
        assert q.options[q.answer_index] == "Pulling information out of your own head"
        positions.add(q.answer_index)
    assert len(positions) > 1


def test_not_json_is_rejected():
    with pytest.raises(BadOutput, match="not valid JSON"):
        parse_study_pack("Sorry, I can't help with that.", INDEX)


def test_missing_overview_is_rejected():
    data = json.loads(pack())
    data["overview"] = "  "
    with pytest.raises(BadOutput, match="overview"):
        parse_study_pack(json.dumps(data), INDEX)


def test_too_few_chapters_is_rejected():
    one = [{"title": "All", "summary": "Everything.", "start_quote": "x"}]
    with pytest.raises(BadOutput, match="chapters"):
        parse_study_pack(pack(chapters=one), INDEX)


@pytest.mark.parametrize("broken", [
    good_question(answer_index=7),
    good_question(answer_index=True),
    good_question(options=["A", "B", "C"]),
    good_question(options=["Same", "same", "C", "D"]),
    good_question(question=""),
])
def test_a_broken_question_is_dropped_and_counted(broken):
    result = parse_study_pack(pack(quiz=[good_question(), good_question(), good_question(), broken]), INDEX)
    assert len(result.quiz) == 3
    assert result.dropped_questions == 1


def test_too_few_usable_questions_is_rejected():
    with pytest.raises(BadOutput, match="usable quiz questions"):
        parse_study_pack(pack(quiz=[good_question(), good_question(answer_index=9)]), INDEX)


def test_invented_evidence_is_kept_but_marked_not_verified():
    invented = good_question(evidence_quote="Arif says flashcards are useless for every kind of student.")
    result = parse_study_pack(pack(quiz=[invented, good_question(), good_question()]), INDEX)
    assert not result.quiz[0].check.verified
    assert result.quotes_verified == result.quotes_total - 1


def test_chapter_spans_cover_the_text_between_chapter_starts():
    result = parse_study_pack(pack(), INDEX)
    first, second = result.chapter_spans(len(SAMPLE))
    assert SAMPLE[first[0]:first[1]].startswith("It's the most common strategy")
    assert first[1] == second[0]
    assert second[1] == len(SAMPLE)


def test_revision_answer_is_read():
    assert parse_overview('{"overview": " Shorter. "}') == "Shorter."
    with pytest.raises(BadOutput):
        parse_overview('{"summary": "wrong key"}')
