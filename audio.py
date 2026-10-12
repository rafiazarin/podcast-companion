"""Checks on an uploaded audio file before any of it is sent to the AI.

The length is read from the file itself, so a 2-hour episode is turned away before
it uses up the free speech-to-text quota.
"""
import io

import mutagen

from config import AUDIO_TYPES, MAX_AUDIO_BYTES, MAX_AUDIO_MINUTES
from transcript import InputError


def is_audio(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[-1].lower() in AUDIO_TYPES


def check_audio(filename: str, data: bytes) -> float:
    """Return the length in seconds, or raise InputError with a message for the user."""
    if not is_audio(filename):
        raise InputError(f"Audio must be one of: {', '.join('.' + t for t in AUDIO_TYPES)}.")
    if len(data) > MAX_AUDIO_BYTES:
        raise InputError(f"This file is {len(data) / 1_000_000:.0f} MB. The limit is "
                         f"{MAX_AUDIO_BYTES // 1_000_000} MB.")
    try:
        info = mutagen.File(io.BytesIO(data))
    except Exception:   # mutagen raises many different errors for damaged files
        info = None
    if info is None or not getattr(info, "info", None) or not info.info.length:
        raise InputError("I couldn't read this audio file. It may be damaged, or not really the type its name says.")
    seconds = float(info.info.length)
    if seconds > MAX_AUDIO_MINUTES * 60:
        raise InputError(f"This audio is {seconds / 60:.0f} minutes long. The free plan handles up to "
                         f"{MAX_AUDIO_MINUTES} minutes. Trim it to one section and upload that.")
    return seconds
