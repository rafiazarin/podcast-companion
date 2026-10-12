"""Tests for the AI step, using a fake backend that fails on purpose. No key or internet needed."""
import json
from pathlib import Path

import groq
import httpx
import pytest

from grounding import TranscriptIndex
from llm import AIError, generate_study_pack, revise_overview
from transcript import InputError

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = (ROOT / "samples" / "sample_transcript.txt").read_text(encoding="utf-8")
INDEX = TranscriptIndex(SAMPLE)
GOOD = (ROOT / "tests" / "fixtures" / "answer_gpt-oss-120b.json").read_text(encoding="utf-8")
REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def status_error(cls, code, headers=None, message="error"):
    return cls(message, response=httpx.Response(code, headers=headers or {}, request=REQUEST), body=None)


class FakeBackend:
    """Plays back a list of outcomes: a string is returned, an exception is raised."""
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def complete(self, system, user, schema_name, schema):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def run(backend, sleeps=None):
    return generate_study_pack(backend, SAMPLE, INDEX, sleep=(sleeps.append if sleeps is not None else None))


def test_success_on_the_first_try_uses_one_request():
    backend = FakeBackend(GOOD)
    assert run(backend).quotes_verified == 9
    assert backend.calls == 1


def test_unusable_answer_is_retried_once():
    backend = FakeBackend("not json at all", GOOD)
    assert run(backend).quotes_total == 9
    assert backend.calls == 2


def test_two_unusable_answers_give_a_clear_message_and_stop():
    backend = FakeBackend("nope", '{"overview": ""}', GOOD)
    with pytest.raises(AIError, match="usable answer"):
        run(backend)
    assert backend.calls == 2   # never a third request


def test_timeout_twice_gives_a_timeout_message():
    backend = FakeBackend(groq.APITimeoutError(request=REQUEST), groq.APITimeoutError(request=REQUEST))
    with pytest.raises(AIError, match="longer than"):
        run(backend)


def test_connection_error_then_success_recovers():
    backend = FakeBackend(groq.APIConnectionError(request=REQUEST), GOOD)
    assert run(backend).quotes_verified == 9


def test_short_rate_limit_is_waited_out():
    sleeps = []
    backend = FakeBackend(status_error(groq.RateLimitError, 429, {"retry-after": "2"}), GOOD)
    assert run(backend, sleeps).quotes_verified == 9
    assert sleeps == [2.0]


def test_long_rate_limit_tells_the_user_when_to_come_back():
    sleeps = []
    backend = FakeBackend(status_error(groq.RateLimitError, 429, {"retry-after": "1800"}))
    with pytest.raises(AIError, match="about 30 minutes"):
        run(backend, sleeps)
    assert sleeps == [] and backend.calls == 1


def test_bad_key_is_not_retried():
    backend = FakeBackend(status_error(groq.AuthenticationError, 401), GOOD)
    with pytest.raises(AIError, match="key"):
        run(backend)
    assert backend.calls == 1


def test_request_too_large_says_so():
    backend = FakeBackend(status_error(groq.APIStatusError, 413))
    with pytest.raises(AIError, match="too long"):
        run(backend)


def test_server_error_is_retried():
    backend = FakeBackend(status_error(groq.InternalServerError, 503), GOOD)
    assert run(backend).quotes_verified == 9


def test_schema_failure_reported_by_groq_is_retried():
    backend = FakeBackend(status_error(groq.BadRequestError, 400, message="json_validate_failed"), GOOD)
    assert run(backend).quotes_verified == 9


def test_revision_returns_only_the_new_overview():
    backend = FakeBackend(json.dumps({"overview": "A shorter overview."}))
    assert revise_overview(backend, SAMPLE, "Old overview.", "shorter") == "A shorter overview."


@pytest.mark.parametrize("request_text", ["", "   ", "x" * 201])
def test_revision_request_must_be_present_and_short(request_text):
    backend = FakeBackend()
    with pytest.raises(InputError):
        revise_overview(backend, SAMPLE, "Old overview.", request_text)
    assert backend.calls == 0   # rejected before any request is sent
