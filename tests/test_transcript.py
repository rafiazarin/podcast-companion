"""Tests for input checks. No API key or internet needed."""
import pytest

from config import MAX_TRANSCRIPT_WORDS, MIN_TRANSCRIPT_WORDS
from transcript import InputError, prepare, read_upload


def words(n):
    return " ".join(["word"] * n)


def test_normal_text_passes_with_its_word_count():
    t = prepare("  " + words(500) + "  ")
    assert t.word_count == 500
    assert t.notices == []


def test_empty_input_is_rejected():
    with pytest.raises(InputError, match="Paste a transcript"):
        prepare("   \n  ")


def test_too_short_is_rejected():
    with pytest.raises(InputError, match="only"):
        prepare(words(MIN_TRANSCRIPT_WORDS - 1))


def test_too_long_is_rejected_with_the_limit_in_the_message():
    with pytest.raises(InputError, match="3,500"):
        prepare(words(MAX_TRANSCRIPT_WORDS + 1))


def test_exactly_at_the_limits_passes():
    assert prepare(words(MIN_TRANSCRIPT_WORDS)).word_count == MIN_TRANSCRIPT_WORDS
    assert prepare(words(MAX_TRANSCRIPT_WORDS)).word_count == MAX_TRANSCRIPT_WORDS


def test_srt_timing_lines_are_removed_and_the_user_is_told():
    cue = "1\n00:00:01,000 --> 00:00:04,000\n" + words(100) + "\n\n2\n00:00:04,500 --> 00:00:09,000\n" + words(100)
    t = prepare(cue)
    assert "-->" not in t.text
    assert t.word_count == 200
    assert "subtitle" in t.notices[0]


def test_vtt_header_and_tags_are_removed():
    vtt = ("WEBVTT\n\n00:01.000 --> 00:04.000\n<c>" + words(100) + "</c>\n\n"
           "00:04.500 --> 00:09.000\n" + words(100))
    t = prepare(vtt)
    assert "WEBVTT" not in t.text and "<c>" not in t.text
    assert t.word_count == 200


def test_one_arrow_in_normal_text_is_not_treated_as_subtitles():
    text = "The plan is 00:01.000 --> later. " + words(200)
    assert prepare(text).notices == []


def test_upload_wrong_type_is_rejected():
    with pytest.raises(InputError, match=".txt"):
        read_upload("episode.pdf", b"data")


def test_upload_not_utf8_is_rejected():
    with pytest.raises(InputError, match="UTF-8"):
        read_upload("episode.txt", "café".encode("latin-1"))


def test_upload_utf8_with_marker_is_read_cleanly():
    assert read_upload("Episode.TXT", "﻿hello".encode("utf-8")) == "hello"


def test_upload_too_big_is_rejected():
    with pytest.raises(InputError, match="KB"):
        read_upload("episode.txt", b"a" * 200_001)
