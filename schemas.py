"""The shape the AI must return, and the checks that turn its answer into something safe to show.

Groq's strict mode already forces the JSON shape. These checks catch what a shape
can't: an answer number that points at no option, duplicate options, empty text,
and quotes that aren't really in the transcript.
"""
import json
import random
from dataclasses import dataclass

from config import MAX_CHAPTERS, MIN_CHAPTERS, MIN_QUIZ_QUESTIONS
from grounding import QuoteCheck, TranscriptIndex


class BadOutput(Exception):
    """The AI's answer can't be used. The message explains why, for the log and for a retry."""


def _object(properties: dict) -> dict:
    # Groq strict mode needs every field listed as required and no extra fields allowed.
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


STUDY_PACK_SCHEMA = _object({
    "overview": {"type": "string"},
    "chapters": {"type": "array", "items": _object({
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "start_quote": {"type": "string"},
    })},
    "quiz": {"type": "array", "items": _object({
        "question": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
        "answer_index": {"type": "integer"},
        "explanation": {"type": "string"},
        "evidence_quote": {"type": "string"},
    })},
})

OVERVIEW_SCHEMA = _object({"overview": {"type": "string"}})


@dataclass
class Chapter:
    title: str
    summary: str
    start_quote: str
    check: QuoteCheck


@dataclass
class Question:
    question: str
    options: list[str]
    answer_index: int
    explanation: str
    evidence_quote: str
    check: QuoteCheck


@dataclass
class StudyPack:
    overview: str
    chapters: list[Chapter]
    quiz: list[Question]
    dropped_questions: int = 0   # questions removed because they were broken

    @property
    def quotes_verified(self) -> int:
        return sum(item.check.verified for item in [*self.chapters, *self.quiz])

    @property
    def quotes_total(self) -> int:
        return len(self.chapters) + len(self.quiz)

    def chapter_spans(self, transcript_length: int) -> list[tuple[int, int] | None]:
        """Where each chapter's text starts and ends. None for a chapter whose quote wasn't found."""
        starts = [c.check.start if c.check.verified else None for c in self.chapters]
        spans = []
        for i, start in enumerate(starts):
            if start is None:
                spans.append(None)
                continue
            later = [s for s in starts[i + 1:] if s is not None]
            spans.append((start, later[0] if later else transcript_length))
        return spans


def _text(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BadOutput(f"{what} is missing or empty.")
    return value.strip()


def parse_overview(raw: str) -> str:
    """Read the answer to a revision request."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise BadOutput("The answer was not valid JSON.") from None
    if not isinstance(data, dict):
        raise BadOutput("The answer was not a JSON object.")
    return _text(data.get("overview"), "The overview")


def parse_study_pack(raw: str, index: TranscriptIndex, rng: random.Random | None = None) -> StudyPack:
    """Turn the AI's JSON into a checked StudyPack, or raise BadOutput."""
    rng = rng or random.Random()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise BadOutput("The answer was not valid JSON.") from None
    if not isinstance(data, dict):
        raise BadOutput("The answer was not a JSON object.")

    overview = _text(data.get("overview"), "The overview")

    raw_chapters = data.get("chapters")
    if not isinstance(raw_chapters, list) or not MIN_CHAPTERS <= len(raw_chapters) <= MAX_CHAPTERS:
        raise BadOutput(f"Expected {MIN_CHAPTERS} to {MAX_CHAPTERS} chapters.")
    titles, summaries, starts = [], [], []
    for n, c in enumerate(raw_chapters, start=1):
        if not isinstance(c, dict):
            raise BadOutput(f"Chapter {n} is not an object.")
        titles.append(_text(c.get("title"), f"Chapter {n}'s title"))
        summaries.append(_text(c.get("summary"), f"Chapter {n}'s summary"))
        starts.append(c.get("start_quote") if isinstance(c.get("start_quote"), str) else "")
    chapters = [Chapter(t, s, q, check)
                for t, s, q, check in zip(titles, summaries, starts, index.find_in_order(starts))]

    raw_quiz = data.get("quiz")
    if not isinstance(raw_quiz, list):
        raise BadOutput("The quiz is missing.")
    quiz, dropped = [], 0
    for q in raw_quiz:
        question = _usable_question(q, index, rng)
        if question is None:
            dropped += 1
        else:
            quiz.append(question)
    if len(quiz) < MIN_QUIZ_QUESTIONS:
        raise BadOutput(f"Only {len(quiz)} usable quiz questions; at least {MIN_QUIZ_QUESTIONS} are needed.")

    return StudyPack(overview, chapters, quiz, dropped)


def _usable_question(q, index: TranscriptIndex, rng: random.Random) -> Question | None:
    """Check one question and shuffle its options. Returns None if the question is broken."""
    if not isinstance(q, dict):
        return None
    options = q.get("options")
    answer = q.get("answer_index")
    if (not isinstance(options, list) or len(options) != 4
            or not all(isinstance(o, str) and o.strip() for o in options)
            or len({o.strip().lower() for o in options}) != 4
            or not isinstance(answer, int) or isinstance(answer, bool) or not 0 <= answer < 4):
        return None
    try:
        text = _text(q.get("question"), "question")
        explanation = _text(q.get("explanation"), "explanation")
    except BadOutput:
        return None
    evidence = q.get("evidence_quote") if isinstance(q.get("evidence_quote"), str) else ""

    # The models put almost every correct answer in position B or C, so shuffle in code.
    order = rng.sample(range(4), 4)
    shuffled = [options[i].strip() for i in order]
    return Question(text, shuffled, order.index(answer), explanation, evidence, index.find(evidence))
