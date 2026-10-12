"""Check that quotes from the AI really appear in the transcript, and find where.

The AI never decides where anything is. It only returns text and quotes. This file
looks each quote up in the transcript, so every position on screen comes from code.

A quote counts as found when it has the same words, in the same order, as some part
of the transcript. Capitals, punctuation, quote styles, dashes and extra spaces are
ignored, because the AI often changes those without changing the meaning.
"""
import unicodedata
from dataclasses import dataclass

from config import MIN_QUOTE_WORDS


@dataclass(frozen=True)
class QuoteCheck:
    """The result of looking up one quote."""
    verified: bool
    start: int | None = None   # position in the original transcript, or None if not found
    end: int | None = None
    reason: str = ""           # why it failed, in plain words; empty when verified


def _is_word_char(ch: str) -> bool:
    # Letters, numbers and combining marks. Marks matter for scripts like Bangla,
    # where vowel signs are separate characters inside a word.
    return unicodedata.category(ch)[0] in "LNM"


def _normalise(text: str) -> tuple[str, list[int]]:
    """Return the text as lowercase words separated by single spaces, plus a map.

    The map says, for each character of the result, which character of the
    original text it came from. That lets us turn a match back into a real position.
    """
    chars: list[str] = []
    origin: list[int] = []
    gap = False
    for i, ch in enumerate(text):
        if _is_word_char(ch):
            if gap and chars:
                chars.append(" ")
                origin.append(i)
            gap = False
            for low in ch.casefold():   # casefold can turn one character into two, e.g. "ß" to "ss"
                chars.append(low)
                origin.append(i)
        else:
            gap = True
    return "".join(chars), origin


class TranscriptIndex:
    """A transcript prepared once, so many quotes can be checked quickly."""

    def __init__(self, transcript: str):
        self.transcript = transcript
        norm, self._origin = _normalise(transcript)
        # Spaces at both ends let us match whole words only: "cram" must not match "cramming".
        self._padded = f" {norm} "

    def _search(self, quote: str, from_pos: int = 0) -> tuple[int | None, int, str]:
        """Find the quote in normalised text. Returns (position or None, length, reason)."""
        q, _ = _normalise(quote)
        if not q:
            return None, 0, "The quote is empty."
        words = len(q.split())
        if words < MIN_QUOTE_WORDS:
            return None, 0, f"The quote is too short ({words} words) to prove anything."
        pos = self._padded.find(f" {q} ", from_pos)
        if pos == -1:
            return None, 0, "The quote was not found in the transcript."
        return pos, len(q), ""

    def _to_check(self, pos: int | None, length: int, reason: str) -> QuoteCheck:
        if pos is None:
            return QuoteCheck(verified=False, reason=reason)
        # pos points at the space before the match in the padded text, which is the
        # same as the first character of the match in the unpadded text.
        start = self._origin[pos]
        end = self._origin[pos + length - 1] + 1
        return QuoteCheck(verified=True, start=start, end=end)

    def find(self, quote: str) -> QuoteCheck:
        """Look up one quote anywhere in the transcript (used for quiz evidence)."""
        return self._to_check(*self._search(quote))

    def find_in_order(self, quotes: list[str]) -> list[QuoteCheck]:
        """Look up chapter start quotes, each one after the previous chapter's start.

        This stops a phrase that appears twice from putting a chapter in the wrong place.
        """
        results = []
        from_pos = 0
        for quote in quotes:
            pos, length, reason = self._search(quote, from_pos)
            if pos is None and not reason.startswith("The quote is"):
                # Not found after the previous chapter. Say so if it exists earlier.
                if self._search(quote)[0] is not None:
                    reason = "The quote appears before the previous chapter, so the order is wrong."
            results.append(self._to_check(pos, length, reason))
            if pos is not None:
                from_pos = pos + 1
        return results
