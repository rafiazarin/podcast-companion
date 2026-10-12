"""Turn what the user pasted or uploaded into clean transcript text, or explain why not.

Every problem becomes an InputError with a message written for the user, so the
app can show it as it is. Nothing here calls the AI, so these checks cost no quota.

If the input carries real timings (subtitle files, YouTube-style transcripts, or
speech-to-text segments), they are kept, so chapters can show when they start.
Times are never guessed: text without timings gets no times.
"""
import bisect
import re
from dataclasses import dataclass, field

from config import MAX_TRANSCRIPT_WORDS, MAX_UPLOAD_BYTES, MIN_TRANSCRIPT_WORDS, TEXT_TYPES


class InputError(Exception):
    """The input can't be used. The message is shown to the user."""


@dataclass
class Transcript:
    text: str
    word_count: int
    notices: list[str] = field(default_factory=list)   # things the user should know
    cue_starts: list[int] = field(default_factory=list)  # where each timed line begins in `text`
    cue_times: list[float] = field(default_factory=list)  # when each timed line begins, in seconds

    @property
    def has_times(self) -> bool:
        return bool(self.cue_starts)

    def seconds_at(self, position: int) -> float | None:
        """The start time of the timed line containing this position, or None if there are no times."""
        if not self.cue_starts:
            return None
        i = bisect.bisect_right(self.cue_starts, position) - 1
        return self.cue_times[max(i, 0)]


# "00:01:02,500 --> 00:01:05,000" (.srt) or "01:02.500 --> 01:05.000" (.vtt)
_SUBTITLE_TIMING = re.compile(r"^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[.,](\d{3})\s*-->")
# A YouTube-style line that starts with a time, e.g. "1:05" or "1:02:05", maybe followed by words
_LEADING_TIME = re.compile(r"^\s*(\d{1,2}(?::\d{2}){1,2})(?:\s+(.*))?$")
_TAG = re.compile(r"<[^>]+>")   # inline subtitle tags such as <c> or <00:00:01.000>


def read_upload(filename: str, data: bytes) -> str:
    """Decode an uploaded text file."""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in TEXT_TYPES:
        raise InputError(f"Please upload a {', '.join('.' + t for t in TEXT_TYPES)} file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise InputError(f"This file is {len(data) // 1000} KB. The limit is {MAX_UPLOAD_BYTES // 1000} KB.")
    try:
        return data.decode("utf-8-sig")   # "-sig" also removes the invisible marker some editors add
    except UnicodeDecodeError:
        raise InputError("This file isn't saved as UTF-8 text. Re-save it as UTF-8 and upload it again.") from None


def _clock_to_seconds(clock: str) -> float:
    seconds = 0.0
    for part in clock.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


def _subtitle_cues(lines: list[str]) -> list[tuple[float, str]] | None:
    """Read .srt/.vtt text into (start seconds, words). None if it isn't a subtitle file."""
    if sum(1 for line in lines if _SUBTITLE_TIMING.match(line)) < 2:
        return None
    cues: list[tuple[float, str]] = []
    current = 0.0
    for line in lines:
        stripped = line.strip()
        timing = _SUBTITLE_TIMING.match(line)
        if timing:
            hours, minutes, secs, millis = timing.groups()
            current = int(hours or 0) * 3600 + int(minutes) * 60 + int(secs) + int(millis) / 1000
            cues.append((current, ""))
            continue
        if not stripped or stripped.isdigit() or stripped.upper().startswith("WEBVTT"):
            continue
        words = _TAG.sub("", stripped)
        if cues:
            cues[-1] = (cues[-1][0], f"{cues[-1][1]} {words}".strip())
        else:
            cues.append((current, words))
    return [cue for cue in cues if cue[1]]


def _youtube_cues(lines: list[str]) -> list[tuple[float, str]] | None:
    """Read 'time on its own line, or at the start of a line' transcripts. None if it isn't one."""
    matches = [(i, _LEADING_TIME.match(line)) for i, line in enumerate(lines)]
    timed = [(i, m) for i, m in matches if m]
    times = [_clock_to_seconds(m.group(1)) for _, m in timed]
    if len(timed) < 3 or times != sorted(times):   # a few stray times in normal text don't count
        return None
    cues: list[tuple[float, str]] = []
    for line, match in matches:
        if match:
            cues.append((_clock_to_seconds(match.group(1)), (match.group(2) or "").strip()))
        elif lines[line].strip():
            start, words = cues[-1] if cues else (0.0, "")
            if cues:
                cues[-1] = (start, f"{words} {lines[line].strip()}".strip())
            else:
                cues.append((0.0, lines[line].strip()))
    return [cue for cue in cues if cue[1]]


def from_cues(cues: list[tuple[float, str]], notices: list[str]) -> "Transcript":
    """Build a timed transcript from (start seconds, words) pairs, one line per cue."""
    starts, times, parts, position = [], [], [], 0
    for seconds, words in cues:
        starts.append(position)
        times.append(seconds)
        parts.append(words)
        position += len(words) + 1   # +1 for the newline that joins the lines
    return _checked("\n".join(parts), notices, starts, times)


def _checked(text: str, notices: list[str], starts=None, times=None) -> Transcript:
    words = len(text.split())
    if words < MIN_TRANSCRIPT_WORDS:
        raise InputError(f"This text is only {words} words. Paste at least {MIN_TRANSCRIPT_WORDS} words "
                         "so there is enough to summarise and quiz on.")
    if words > MAX_TRANSCRIPT_WORDS:
        raise InputError(f"This transcript is {words:,} words. The free plan handles up to "
                         f"{MAX_TRANSCRIPT_WORDS:,} words per run (about 20 to 25 minutes of speech). "
                         "Paste a shorter section.")
    return Transcript(text, words, notices, starts or [], times or [])


def prepare(raw: str) -> Transcript:
    """Check the size, clean the text, and keep any real timings. Raises InputError for the user."""
    text = (raw or "").strip()
    if not text:
        raise InputError("Paste a transcript or upload a file first.")
    lines = text.splitlines()

    cues = _subtitle_cues(lines)
    if cues is not None:
        return from_cues(cues, ["This looks like a subtitle file. I kept the words and their timings, "
                                "so chapters show when they start."])
    cues = _youtube_cues(lines)
    if cues is not None:
        return from_cues(cues, ["This transcript has times in it. I kept them, so chapters show when they start."])
    return _checked(text, [])
