"""Turn results into text for the screen and for download. No Streamlit and no AI here."""
import html

from schemas import StudyPack

LETTERS = "ABCD"


def excerpt_html(text: str, show_start: int, show_end: int, mark_start: int, mark_end: int) -> str:
    """A piece of the transcript as safe HTML, with one part highlighted.

    Everything is escaped first, so text in a transcript like "<script>" is shown, never run.
    """
    show_start, show_end = max(0, show_start), min(len(text), show_end)
    # Don't start or end in the middle of a word, and never cut into the highlighted part.
    while 0 < show_start < mark_start and not text[show_start - 1].isspace():
        show_start += 1
    while mark_end < show_end < len(text) and not text[show_end].isspace():
        show_end -= 1

    def esc(part: str) -> str:
        return html.escape(part).replace("\n", "<br>")

    before = ("…" if show_start > 0 else "") + esc(text[show_start:mark_start])
    after = esc(text[mark_end:show_end]) + ("…" if show_end < len(text) else "")
    return f'<div class="transcript">{before}<mark>{esc(text[mark_start:mark_end])}</mark>{after}</div>'


def trust_line(pack: StudyPack) -> str:
    return f"{pack.quotes_verified} of {pack.quotes_total} quotes were found in the transcript."


def to_markdown(pack: StudyPack, overview: str, notices: list[str]) -> str:
    """Everything in one Markdown document, including answers and which quotes were verified."""
    def mark(check) -> str:
        return "found in transcript" if check.verified else "NOT found in transcript"

    lines = ["# Podcast study pack", "", f"_{trust_line(pack)} Checked by code, not by the AI._", ""]
    lines += [f"> {n}" for n in notices] + ([""] if notices else [])
    lines += ["## Overview", "", overview, "", "## Chapters", ""]
    for i, c in enumerate(pack.chapters, start=1):
        lines += [f"### {i}. {c.title}", "", c.summary, "", f"Starts with: \"{c.start_quote}\" ({mark(c.check)})", ""]
    lines += ["## Quiz", ""]
    for i, q in enumerate(pack.quiz, start=1):
        lines += [f"**{i}. {q.question}**", ""]
        lines += [f"- {LETTERS[j]}. {option}" for j, option in enumerate(q.options)]
        lines += ["", f"Answer: {LETTERS[q.answer_index]}. {q.options[q.answer_index]}",
                  f"Why: {q.explanation}", f"Evidence: \"{q.evidence_quote}\" ({mark(q.check)})", ""]
    lines += ["---", "Timestamps are not included: this version works from text only."]
    return "\n".join(lines)
