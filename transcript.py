"""Turn what the user pasted or uploaded into clean transcript text, or explain why not.

Every problem becomes an InputError with a message written for the user, so the
app can show it as it is. Nothing here calls the AI, so these checks cost no quota.
"""
import re
from dataclasses import dataclass, field

from config import MAX_TRANSCRIPT_WORDS, MAX_UPLOAD_BYTES, MIN_TRANSCRIPT_WORDS, UPLOAD_TYPES


class InputError(Exception):
    """The input can't be used. The message is shown to the user."""


@dataclass
class Transcript:
    text: str
    word_count: int
    notices: list[str] = field(default_factory=list)   # things the user should know, e.g. timings removed


# A subtitle timing line, e.g. "00:01:02,500 --> 00:01:05,000" (.srt) or "01:02.500 --> 01:05.000" (.vtt)
_TIMING_LINE = re.compile(r"^\s*(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3}\s*-->")
_TAG = re.compile(r"<[^>]+>")   # inline subtitle tags such as <c> or <00:00:01.000>


def read_upload(filename: str, data: bytes) -> str:
    """Decode an uploaded file into text."""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in UPLOAD_TYPES:
        raise InputError(f"Please upload a {', '.join('.' + t for t in UPLOAD_TYPES)} file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise InputError(f"This file is {len(data) // 1000} KB. The limit is {MAX_UPLOAD_BYTES // 1000} KB.")
    try:
        return data.decode("utf-8-sig")   # "-sig" also removes the invisible marker some editors add
    except UnicodeDecodeError:
        raise InputError("This file isn't saved as UTF-8 text. Re-save it as UTF-8 and upload it again.") from None


def _strip_subtitle_timing(text: str) -> tuple[str, bool]:
    """If the text is a subtitle file, keep only the spoken words."""
    lines = text.splitlines()
    if sum(1 for line in lines if _TIMING_LINE.match(line)) < 2:
        return text, False
    kept = []
    for line in lines:
        stripped = line.strip()
        if _TIMING_LINE.match(line) or stripped.isdigit() or stripped.upper().startswith("WEBVTT"):
            continue
        kept.append(_TAG.sub("", line))
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return cleaned, True


def prepare(raw: str) -> Transcript:
    """Check the size and clean the text. Raises InputError with a user-facing message."""
    text = (raw or "").strip()
    if not text:
        raise InputError("Paste a transcript or upload a file first.")

    notices = []
    text, was_subtitles = _strip_subtitle_timing(text)
    if was_subtitles:
        notices.append("This looks like a subtitle file. I removed the timing lines and kept the words. "
                       "This version doesn't show timestamps.")

    words = len(text.split())
    if words < MIN_TRANSCRIPT_WORDS:
        raise InputError(f"This text is only {words} words. Paste at least {MIN_TRANSCRIPT_WORDS} words "
                         "so there is enough to summarise and quiz on.")
    if words > MAX_TRANSCRIPT_WORDS:
        raise InputError(f"This transcript is {words:,} words. The free plan handles up to "
                         f"{MAX_TRANSCRIPT_WORDS:,} words per run (about 20 to 25 minutes of speech). "
                         "Paste a shorter section.")
    return Transcript(text=text, word_count=words, notices=notices)
