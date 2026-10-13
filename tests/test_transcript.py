"""Tests for input checks. No API key or internet needed."""
import pytest

from config import MAX_TRANSCRIPT_WORDS, MIN_TRANSCRIPT_WORDS
from grounding import TranscriptIndex
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


def youtube_copy(captions):
    """Captions in the layout YouTube copies today: each time on its own line, then a short line of speech."""
    return "\n".join(f"{i // 60}:{i % 60:02d}\n{line}" for i, line in zip(range(0, 10_000, 3), captions))


def test_spoken_clock_time_at_the_start_of_a_caption_line_does_not_lose_the_timings():
    # A real bug: "10:00 a.m." looked like a time going backwards, so every timing was dropped,
    # the times stayed in the text as words, and quotes across caption lines couldn't be found.
    captions = [f"the guest explains part {n} of the idea in short words" for n in range(40)]
    captions[20] = "10:00 a.m. is when she likes to wake up"
    t = prepare(youtube_copy(captions))
    assert t.has_times and len(t.cue_times) == 40
    assert t.cue_times == sorted(t.cue_times)
    assert "10:00 a.m. is when she likes to wake up" in t.text
    assert "\n0:03" not in t.text and "1:00" not in t.text


def test_a_quote_across_caption_lines_is_found_with_its_time():
    captions = [f"line {n} has some ordinary spoken words" for n in range(40)]
    captions[10:12] = ["the most important habit is to", "test yourself and spread it out"]
    t = prepare(youtube_copy(captions))
    check = TranscriptIndex(t.text).find("the most important habit is to test yourself and spread it out")
    assert check.verified
    assert t.seconds_at(check.start) == 30


def test_sound_labels_are_removed():
    captions = ["[Music]"] + [f"[laughter] line {n} has some ordinary words [snorts] here" for n in range(40)]
    t = prepare(youtube_copy(captions))
    assert "[" not in t.text and "laughter" not in t.text and "Music" not in t.text
    assert "[" not in prepare("[Applause] " + words(200)).text


def spoken(seconds):
    """The hidden label YouTube adds after a time: 64 -> "1 minute, 4 seconds"."""
    minutes, secs = divmod(seconds, 60)
    parts = [f"{minutes} minute{'s' * (minutes != 1)}"] if minutes else []
    if secs or not minutes:
        parts.append(f"{secs} second{'s' * (secs != 1)}")
    return ", ".join(parts)


def test_youtube_copy_with_glued_spoken_labels_and_chapter_headings():
    # Some browsers copy the hidden label glued to the words: "1:041 minute, 4 secondsvery prepared".
    lines = ["Chapter 1: Getting started"]
    for n in range(40):
        seconds = n * 31
        lines.append(f"{seconds // 60}:{seconds % 60:02d}{spoken(seconds)}speech part {n} goes on with words")
        if n == 20:
            lines.append("Chapter 2: The middle part")
    t = prepare("\n".join(lines))
    assert t.has_times and len(t.cue_times) == 40
    assert t.cue_times[:3] == [0, 31, 62]
    assert "Chapter" not in t.text and "second" not in t.text and "minute" not in t.text
    assert t.text.startswith("speech part 0 goes on")
    assert "speech part 20 goes on with words\nspeech part 21" in t.text


def test_a_label_that_does_not_match_the_clock_is_kept_as_speech():
    lines = [f"{n}:00 the host talks about part {n} of the story" for n in range(40)]
    lines[2] = "2:00 5 seconds later the guest answered"
    assert "5 seconds later the guest answered" in prepare("\n".join(lines)).text


def test_a_one_unit_label_gives_back_the_s_of_the_next_word():
    lines = [f"{n}:00{spoken(n * 60)}some words here for part {n} of it" for n in range(40)]
    t = prepare("\n".join(lines))
    assert "some words here for part 1 of it" in t.text
    assert t.cue_times[1] == 60


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
