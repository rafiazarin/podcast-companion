"""Tests for audio checks. They use small audio files made in memory."""
import io
import wave

import pytest

from audio import check_audio, is_audio
from config import MAX_AUDIO_MINUTES
from transcript import InputError, from_cues


def wav_bytes(seconds: float, rate: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(rate)
        w.writeframes(b"\x80" * int(rate * seconds))
    return buffer.getvalue()


def test_a_short_wav_passes_and_reports_its_length():
    assert check_audio("talk.WAV", wav_bytes(3)) == pytest.approx(3.0)


def test_audio_longer_than_the_limit_is_rejected_before_any_upload():
    with pytest.raises(InputError, match="minutes long"):
        check_audio("long.wav", wav_bytes(MAX_AUDIO_MINUTES * 60 + 5, rate=100))


def test_a_text_file_renamed_to_mp3_is_rejected():
    with pytest.raises(InputError, match="couldn't read"):
        check_audio("fake.mp3", b"this is not audio at all")


def test_unsupported_audio_type_is_rejected():
    assert not is_audio("talk.aac")
    with pytest.raises(InputError, match="Audio must be"):
        check_audio("talk.aac", b"x")


def test_speech_segments_become_a_timed_transcript():
    cues = [(0.0, "word " * 80), (95.5, "word " * 80)]
    t = from_cues(cues, [])
    assert t.has_times
    assert t.seconds_at(0) == 0.0
    assert t.seconds_at(len(t.text) - 1) == 95.5
