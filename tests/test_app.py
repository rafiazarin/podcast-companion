"""End-to-end tests of the real screen (app.py), with a fake AI. No key or internet needed.

Streamlit's AppTest runs app.py like a browser would: we type, click and read what is shown.
"""
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import llm
from config import MAX_RUNS_PER_SESSION

ROOT = Path(__file__).resolve().parent.parent
GOOD = (ROOT / "tests" / "fixtures" / "answer_gpt-oss-120b.json").read_text(encoding="utf-8")
SAMPLE = (ROOT / "samples" / "sample_transcript.txt").read_text(encoding="utf-8")


class FakeBackend:
    def __init__(self):
        self.queue = []      # outcomes to play first; after that, normal good answers
        self.calls = []

    def complete(self, system, user, schema_name, schema):
        self.calls.append(schema_name)
        if self.queue:
            outcome = self.queue.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return GOOD if schema_name == "study_pack" else '{"overview": "A shorter overview from the fake AI."}'


@pytest.fixture
def fake(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(llm, "GroqBackend", lambda key: backend)
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    st.cache_resource.clear()
    return backend


def start():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.run()
    return at


def button(at, label):
    return next(b for b in at.button if b.label == label)


def generate_sample(at):
    button(at, "Try a sample episode").click().run()
    button(at, "Generate study pack").click().run()
    return at


def texts(elements):
    return " ".join(str(e.value) for e in elements)


def test_page_loads_and_generate_is_disabled_while_empty(fake):
    at = start()
    assert not at.exception
    assert button(at, "Generate study pack").disabled


def test_sample_generates_a_full_study_pack(fake):
    at = generate_sample(start())
    assert not at.exception
    assert "9 of 9 quotes were found" in texts(at.success)
    assert len(at.radio) == 5
    assert fake.calls == ["study_pack"]


def test_sample_a_second_time_uses_no_ai_request(fake):
    at = generate_sample(start())
    button(at, "Generate study pack").click().run()
    assert fake.calls == ["study_pack"]
    assert "no AI request used" in texts(at.caption)


def test_too_short_text_is_stopped_before_any_ai_request(fake):
    at = start()
    at.text_area(key="transcript_text").input("Just a few words.").run()
    button(at, "Generate study pack").click().run()
    assert "only 4 words" in texts(at.warning)
    assert fake.calls == []


def test_ai_failure_shows_a_message_not_a_crash(fake):
    fake.queue = ["not json", "still not json"]
    at = start()
    at.text_area(key="transcript_text").input(SAMPLE + " extra").run()   # not the cached sample
    button(at, "Generate study pack").click().run()
    assert not at.exception
    assert "usable answer" in texts(at.error)


def test_revision_changes_only_the_overview(fake):
    at = generate_sample(start())
    button(at, "Shorter").click().run()
    assert "A shorter overview from the fake AI." in texts(at.markdown)
    assert fake.calls == ["study_pack", "overview"]
    assert len(at.radio) == 5   # quiz untouched
    button(at, "Undo last change").click().run()
    assert "A shorter overview from the fake AI." not in texts(at.markdown)


def test_all_correct_answers_score_full_marks(fake):
    at = generate_sample(start())
    pack = at.session_state["result"]["pack"]
    for radio, question in zip(at.radio, pack.quiz):
        radio.set_value(question.answer_index)
    button(at, "Check my answers").click().run()
    assert any("Score: 5 / 5" in s.value for s in at.subheader)


def test_missing_key_is_explained(fake, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")
    at = start()
    at.text_area(key="transcript_text").input(SAMPLE + " extra").run()
    button(at, "Generate study pack").click().run()
    assert "isn't set up with an AI key" in texts(at.error)


def test_visit_limit_stops_more_requests(fake):
    at = start()
    at.session_state["runs"] = MAX_RUNS_PER_SESSION
    at.text_area(key="transcript_text").input(SAMPLE + " extra").run()
    button(at, "Generate study pack").click().run()
    assert "used all" in texts(at.warning)
    assert fake.calls == []


def test_request_counter_includes_a_revision(fake):
    at = start()
    at.text_area(key="transcript_text").input(SAMPLE + " extra").run()
    button(at, "Generate study pack").click().run()
    button(at, "Shorter").click().run()
    assert f"{MAX_RUNS_PER_SESSION - 2} AI requests left" in texts(at.caption)


def youtube_style(text):
    """The sample with a time line before every paragraph, like a copied YouTube transcript."""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    return "\n".join(f"{i // 2}:{(i % 2) * 30:02d}\n{p}" for i, p in enumerate(paragraphs))


def test_transcript_with_times_shows_chapter_times(fake):
    at = start()
    at.text_area(key="transcript_text").input(youtube_style(SAMPLE)).run()
    button(at, "Generate study pack").click().run()
    assert not at.exception
    assert "9 of 9 quotes were found" in texts(at.success)
    assert all("·" in e.label for e in at.expander if e.label[:1].isdigit())
    assert "has times in it" in texts(at.info)


def test_plain_text_says_no_times_are_shown(fake):
    at = generate_sample(start())
    assert "never guesses them" in texts(at.caption)
    assert not any("·" in e.label for e in at.expander if e.label[:1].isdigit())


def test_loading_the_sample_empties_the_upload_box(fake):
    at = start()
    before = at.session_state["uploader_key"]
    button(at, "Try a sample episode").click().run()
    assert at.session_state["uploader_key"] == before + 1
    assert at.text_area(key="transcript_text").value == SAMPLE
