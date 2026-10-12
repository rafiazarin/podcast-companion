"""Calls to the AI (Groq), with timeouts, limited retries and messages a user can understand.

Every failure ends as an AIError whose message can be shown on screen. The real
reason goes to the log, without the transcript or the key.
"""
import logging
import random
import time
from typing import Callable, Protocol

import groq

import prompts
from config import (MAX_ATTEMPTS, MAX_REVISION_CHARS, MAX_WAIT_SECONDS, MODEL, REASONING_EFFORT,
                    TIMEOUT_SECONDS)
from grounding import TranscriptIndex
from schemas import OVERVIEW_SCHEMA, STUDY_PACK_SCHEMA, BadOutput, StudyPack, parse_overview, parse_study_pack
from transcript import InputError

log = logging.getLogger(__name__)


class AIError(Exception):
    """The AI step failed. The message is written for the user."""


class Backend(Protocol):
    """Anything that can send one request and return the raw text. Tests use a fake one."""
    def complete(self, system: str, user: str, schema_name: str, schema: dict) -> str: ...


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


def _call(backend: Backend, system: str, user: str, schema_name: str, schema: dict,
          parse: Callable[[str], object], sleep: Callable[[float], None]):
    """Send one request, retrying once on problems that a retry can fix."""
    problem = "unknown"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.perf_counter()
        try:
            result = parse(backend.complete(system, user, schema_name, schema))
            log.info("AI call ok: %s attempt=%d seconds=%.1f", schema_name, attempt, time.perf_counter() - started)
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
                raise AIError("This transcript is too long for the free AI plan. "
                              "Paste a shorter section.") from None
            log.error("AI service returned %s", error.status_code)
            raise AIError("The AI service returned an error. Please try again.") from None

    messages = {
        "bad_output": "The AI couldn't produce a usable answer for this transcript after two tries. "
                      "Try again, or paste a cleaner or shorter section.",
        "timeout": f"The AI took longer than {TIMEOUT_SECONDS} seconds to respond, twice. Please try again.",
        "connection": "The app couldn't reach the AI service. Check back in a minute.",
        "server": "The AI service is having problems right now. Please try again in a minute.",
    }
    raise AIError(messages.get(problem, "Something went wrong with the AI step. Please try again."))


def generate_study_pack(backend: Backend, transcript: str, index: TranscriptIndex,
                        rng: random.Random | None = None, sleep: Callable[[float], None] = time.sleep) -> StudyPack:
    """Make the overview, chapters and quiz in one request."""
    return _call(backend, prompts.STUDY_PACK, prompts.study_pack_message(transcript),
                 "study_pack", STUDY_PACK_SCHEMA, lambda raw: parse_study_pack(raw, index, rng), sleep)


def revise_overview(backend: Backend, transcript: str, overview: str, request: str,
                    sleep: Callable[[float], None] = time.sleep) -> str:
    """Rewrite only the overview. The chapters and quiz are not touched or regenerated."""
    request = (request or "").strip()
    if not request:
        raise InputError("Say how you'd like the summary changed, for example \"shorter\".")
    if len(request) > MAX_REVISION_CHARS:
        raise InputError(f"Please keep the request under {MAX_REVISION_CHARS} characters.")
    return _call(backend, prompts.REVISE_OVERVIEW, prompts.revise_message(transcript, overview, request),
                 "overview", OVERVIEW_SCHEMA, parse_overview, sleep)
