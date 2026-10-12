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


def test_srt_keeps_words_and_their_real_times():
    cue = ("1\n00:00:01,000 --> 00:00:04,000\n" + words(100) + "\n\n"
           "2\n00:01:04,500 --> 00:01:09,000\n" + words(100))
    t = prepare(cue)
    assert "-->" not in t.text
    assert t.word_count == 200
    assert t.has_times
    assert t.seconds_at(0) == 1.0
    assert t.seconds_at(len(t.text) - 1) == 64.5
    assert "subtitle" in t.notices[0]


def test_vtt_header_and_tags_are_removed():
    vtt = ("WEBVTT\n\n00:01.000 --> 00:04.000\n<c>" + words(100) + "</c>\n\n"
           "00:04.500 --> 00:09.000\n" + words(100))
    t = prepare(vtt)
    assert "WEBVTT" not in t.text and "<c>" not in t.text
    assert t.word_count == 200
    assert t.cue_times == [1.0, 4.5]


def test_youtube_style_times_on_their_own_lines_are_kept():
    yt = "0:00\n" + words(60) + "\n0:45\n" + words(60) + "\n1:02:03\n" + words(60)
    t = prepare(yt)
    assert t.cue_times == [0, 45, 3723]
    assert t.word_count == 180
    assert "0:45" not in t.text


def test_youtube_style_times_at_the_start_of_lines_are_kept():
    yt = "\n".join(f"{m}:00 " + words(40) for m in range(5))
    t = prepare(yt)
    assert t.cue_times == [0, 60, 120, 180, 240]


def test_plain_text_has_no_times():
    t = prepare(words(300))
    assert not t.has_times
    assert t.seconds_at(10) is None


def test_times_out_of_order_are_not_treated_as_a_timed_transcript():
    text = "\n".join(["5:00 " + words(60), "1:00 " + words(60), "3:00 " + words(60)])
    assert not prepare(text).has_times


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
