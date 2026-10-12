"""Probe: on one real transcript, does each model return valid structure and exact quotes?"""
import json
import re
import time
from pathlib import Path

from groq import Groq

TRANSCRIPT = Path("samples/sample_transcript.txt").read_text(encoding="utf-8")
MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]

SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "start_quote": {"type": "string"},
                },
                "required": ["title", "summary", "start_quote"],
                "additionalProperties": False,
            },
        },
        "quiz": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer_index": {"type": "integer"},
                    "explanation": {"type": "string"},
                    "evidence_quote": {"type": "string"},
                },
                "required": ["question", "options", "answer_index", "explanation", "evidence_quote"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overview", "chapters", "quiz"],
    "additionalProperties": False,
}

INSTRUCTIONS = """You turn a podcast transcript into study material.
Use only information stated in the transcript. Do not add outside facts.
Write a short overview of 3 to 5 sentences.
Split the episode into 3 to 6 chapters, in order. For each chapter, start_quote is
the exact sentence where that chapter begins, copied word for word.
Write 5 multiple-choice questions with 4 options each. answer_index is 0 to 3.
evidence_quote is the exact sentence from the transcript that proves the answer,
copied word for word. Never include the speaker's name in a quote."""


def normalise(text):
    """Lowercase, straighten curly quotes, collapse spaces, so small format differences don't count."""
    text = text.lower()
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip()


def found(quote, transcript):
    """True only if the quote is non-empty and appears in the transcript."""
    q = normalise(quote)
    return bool(q) and q in normalise(transcript)


def main():
    client = Groq()  # reads GROQ_API_KEY from the environment
    for model in MODELS:
        start = time.perf_counter()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": INSTRUCTIONS},
                    {"role": "user", "content": TRANSCRIPT},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "study_pack", "strict": True, "schema": SCHEMA},
                },
                reasoning_effort="low",
            )
            data = json.loads(response.choices[0].message.content)
        except Exception as error:  # a throwaway probe: print any failure and move on
            print(f"\n{model}: FAILED: {error}")
            continue
        seconds = time.perf_counter() - start

        Path(f"probes/out_{model.split('/')[1]}.json").write_text(json.dumps(data, indent=2))
        quotes = [c["start_quote"] for c in data["chapters"]] + [q["evidence_quote"] for q in data["quiz"]]
        hits = sum(found(q, TRANSCRIPT) for q in quotes)
        usage = response.usage

        print(f"\n{model}: {seconds:.1f} s, tokens in {usage.prompt_tokens}, out {usage.completion_tokens}")
        print(f"  chapters {len(data['chapters'])}, quiz {len(data['quiz'])}, quotes found {hits}/{len(quotes)}")
        for q in quotes:
            if not found(q, TRANSCRIPT):
                print("  NOT FOUND:", q)
        for i, q in enumerate(data["quiz"]):
            if not 0 <= q["answer_index"] < len(q["options"]):
                print(f"  question {i + 1} has an answer_index outside its options")


if __name__ == "__main__":
    main()
