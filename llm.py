"""Calls to the AI (Groq), with timeouts, limited retries and messages a user can understand.

Every failure ends as an AIError whose message can be shown on screen. The real
reason goes to the log, without the transcript or the key.
"""
import logging
import random
import time
from typing import Callable, Protocol, TypeVar

import groq

import prompts
from config import (MAX_ATTEMPTS, MAX_REVISION_CHARS, MAX_WAIT_SECONDS, MODEL, REASONING_EFFORT,
                    TIMEOUT_SECONDS, TRANSCRIBE_MODEL)
from grounding import TranscriptIndex
from schemas import OVERVIEW_SCHEMA, STUDY_PACK_SCHEMA, BadOutput, StudyPack, parse_overview, parse_study_pack
from transcript import InputError

log = logging.getLogger(__name__)
T = TypeVar("T")


class AIError(Exception):
    """The AI step failed. The message is written for the user."""


class Backend(Protocol):
    """Anything that can send one request and return the raw text. Tests use a fake one."""
    def complete(self, system: str, user: str, schema_name: str, schema: dict) -> str: ...
    def transcribe(self, filename: str, data: bytes) -> list[dict]: ...


class GroqBackend:
    def __init__(self, api_key: str):
        # max_retries=0: the library's own retries are switched off, so this file decides
        # exactly when to retry and how many requests a run can use.
        self._client = groq.Groq(api_key=api_key, timeout=TIMEOUT_SECONDS, max_retries=0)

    def complete(self, system: str, user: str, schema_name: str, schema: dict) -> str:
        response = self._client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
            reasoning_effort=REASONING_EFFORT,
        )
        return response.choices[0].message.content or ""

    def transcribe(self, filename: str, data: bytes) -> list[dict]:
        """Speech to text. Returns Whisper's segments: each has a start time in seconds and its text."""
        response = self._client.audio.transcriptions.create(
            file=(filename, data), model=TRANSCRIBE_MODEL, response_format="verbose_json")
        return response.model_dump().get("segments") or []


def _retry_after(error: groq.APIStatusError) -> float | None:
    try:
        return float(error.response.headers.get("retry-after"))
    except (TypeError, ValueError):
        return None


def _wait_text(seconds: float) -> str:
    if seconds < 90:
        return f"about {max(1, round(seconds))} seconds"
    if seconds < 5400:
        return f"about {round(seconds / 60)} minutes"
    return f"about {round(seconds / 3600)} hours"


def _with_retries(action: Callable[[], T], label: str, sleep: Callable[[float], None]) -> T:
    """Run one AI request (and the check of its answer), retrying once on problems a retry can fix."""
    problem = "unknown"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.perf_counter()
        try:
            result = action()
            log.info("AI call ok: %s attempt=%d seconds=%.1f", label, attempt, time.perf_counter() - started)
            return result
        except BadOutput as error:
            problem = "bad_output"
            log.warning("Unusable AI answer (attempt %d): %s", attempt, error)
        except groq.APITimeoutError:   # must come before APIConnectionError, which it is a kind of
            problem = "timeout"
            log.warning("AI call timed out after %ss (attempt %d)", TIMEOUT_SECONDS, attempt)
        except groq.APIConnectionError:
            problem = "connection"
            log.warning("Could not reach the AI service (attempt %d)", attempt)
        except groq.RateLimitError as error:
            wait = _retry_after(error)
            log.warning("Rate limited (attempt %d), retry-after=%s", attempt, wait)
            if wait is not None and wait <= MAX_WAIT_SECONDS and attempt < MAX_ATTEMPTS:
                sleep(wait)
                continue
            when = _wait_text(wait) if wait is not None else "a minute"
            raise AIError(f"The free AI plan is at its limit right now. Please try again in {when}.") from None
        except (groq.AuthenticationError, groq.PermissionDeniedError):
            log.error("The AI service rejected the API key")
            raise AIError("The app's AI key isn't working. This is a problem on my side, "
                          "not with your transcript.") from None
        except groq.InternalServerError as error:
            problem = "server"
            log.warning("AI service error %s (attempt %d)", error.status_code, attempt)
        except groq.BadRequestError as error:
            if "json_validate_failed" in str(error):
                problem = "bad_output"
                log.warning("AI answer failed the JSON schema (attempt %d)", attempt)
            else:
                log.error("AI request rejected: %s", error)
                raise AIError("The AI service rejected the request. Please try again.") from None
        except groq.APIStatusError as error:
            if error.status_code == 413:
                raise AIError("This is too large for the free AI plan. "
                              "Try a shorter section.") from None
            log.error("AI service returned %s", error.status_code)
            raise AIError("The AI service returned an error. Please try again.") from None

    messages = {
        "bad_output": "The AI couldn't produce a usable answer for this after two tries. "
                      "Try again, or use a cleaner or shorter section.",
        "timeout": f"The AI took longer than {TIMEOUT_SECONDS} seconds to respond, twice. Please try again.",
        "connection": "The app couldn't reach the AI service. Check back in a minute.",
        "server": "The AI service is having problems right now. Please try again in a minute.",
    }
    raise AIError(messages.get(problem, "Something went wrong with the AI step. Please try again."))


def generate_study_pack(backend: Backend, transcript: str, index: TranscriptIndex,
                        rng: random.Random | None = None, sleep: Callable[[float], None] = time.sleep) -> StudyPack:
    """Make the overview, chapters and quiz in one request."""
    message = prompts.study_pack_message(transcript)
    return _with_retries(
        lambda: parse_study_pack(backend.complete(prompts.STUDY_PACK, message, "study_pack", STUDY_PACK_SCHEMA),
                                 index, rng),
        "study_pack", sleep)


def revise_overview(backend: Backend, transcript: str, overview: str, request: str,
                    sleep: Callable[[float], None] = time.sleep) -> str:
    """Rewrite only the overview. The chapters and quiz are not touched or regenerated."""
    request = (request or "").strip()
    if not request:
        raise InputError("Say how you'd like the summary changed, for example \"shorter\".")
    if len(request) > MAX_REVISION_CHARS:
        raise InputError(f"Please keep the request under {MAX_REVISION_CHARS} characters.")
    message = prompts.revise_message(transcript, overview, request)
    return _with_retries(
        lambda: parse_overview(backend.complete(prompts.REVISE_OVERVIEW, message, "overview", OVERVIEW_SCHEMA)),
        "overview", sleep)


def _segments_to_cues(segments) -> list[tuple[float, str]]:
    cues = []
    for segment in segments if isinstance(segments, list) else []:
        if not isinstance(segment, dict):
            continue
        text, start = (segment.get("text") or "").strip(), segment.get("start")
        if text and isinstance(start, (int, float)):
            cues.append((float(start), text))
    if not cues:
        raise BadOutput("Speech-to-text returned no usable segments.")
    return cues


def transcribe_audio(backend: Backend, filename: str, data: bytes,
                     sleep: Callable[[float], None] = time.sleep) -> list[tuple[float, str]]:
    """Turn audio into (start seconds, text) lines. Raises AIError with a message for the user."""
    return _with_retries(lambda: _segments_to_cues(backend.transcribe(filename, data)), "transcription", sleep)
