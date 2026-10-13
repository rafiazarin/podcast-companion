"""The screen. Only this file uses Streamlit. All real logic lives in plain Python modules."""
import hashlib
import logging
import os
import time
from pathlib import Path

import streamlit as st

import llm
from audio import check_audio, is_audio
from config import (MAX_AUDIO_MINUTES, MAX_RUNS_PER_SESSION, MAX_TRANSCRIPT_WORDS, MIN_QUOTE_WORDS, MODEL,
                    TRANSCRIBE_MODEL, UPLOAD_TYPES)
from formatting import LETTERS, clock, excerpt_html, to_markdown, trust_line
from grounding import TranscriptIndex
from transcript import InputError, Transcript, from_cues, prepare, read_upload

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

SAMPLE_TEXT = (Path(__file__).parent / "samples" / "sample_transcript.txt").read_text(encoding="utf-8")
REVISION_PRESETS = {"Shorter": "Make it shorter: two or three sentences.",
                    "Simpler words": "Use simpler, everyday words.",
                    "More detail": "Add more detail about each main idea."}

st.set_page_config(page_title="Podcast Companion", page_icon="🎧", layout="centered")
st.markdown("""<style>
.transcript {border-left: 3px solid #999; padding: 0.4rem 0.8rem; margin: 0.3rem 0 0.8rem 0;
             line-height: 1.55; font-size: 0.95rem;}
.transcript mark {background: #ffe58a; color: #111; padding: 0 2px;}
</style>""", unsafe_allow_html=True)


# ---------- setup ----------

def api_key() -> str | None:
    """The key comes from the host's secrets store or an environment variable, never from code."""
    if os.environ.get("GROQ_API_KEY"):
        return os.environ["GROQ_API_KEY"]
    try:
        return st.secrets["GROQ_API_KEY"]
    except Exception:   # st.secrets raises different errors when there's no secrets file or no such key
        return None


@st.cache_resource
def backend() -> llm.Backend | None:
    key = api_key()
    return llm.GroqBackend(key) if key else None


@st.cache_resource
def sample_store() -> dict:
    """Keeps the result for the built-in sample only, so trying the sample costs no quota.
    Nothing a visitor pastes is kept."""
    return {}


state = st.session_state
state.setdefault("runs", 0)
state.setdefault("result", None)
state.setdefault("result_id", 0)
state.setdefault("uploader_key", 0)      # changing this empties the upload box
state.setdefault("transcriptions", {})   # speech-to-text results for this visit, so the same file isn't sent twice


def runs_left() -> int:
    return MAX_RUNS_PER_SESSION - state.runs


# ---------- actions ----------

def generate(raw: str, source: str) -> None:
    """Make a study pack from pasted or uploaded text."""
    try:
        transcript = prepare(raw)
    except InputError as problem:
        st.warning(str(problem))
        return

    is_sample = transcript.text == SAMPLE_TEXT.strip()
    store = sample_store()
    if is_sample and "pack" in store:
        save_result(store["pack"], transcript, raw.strip(), source, seconds=None, cached=True)
        return
    pack, seconds = make_pack(transcript)
    if pack is None:
        return
    if is_sample:
        store["pack"] = pack
    save_result(pack, transcript, raw.strip(), source, seconds, cached=False)


def generate_from_audio(filename: str, data: bytes) -> None:
    """Turn audio into a timed transcript (once per file), then make a study pack from it."""
    try:
        length = check_audio(filename, data)
    except InputError as problem:
        st.warning(str(problem))
        return
    digest = hashlib.sha256(data).hexdigest()
    cues = state.transcriptions.get(digest)
    if cues is None:
        if not ready_for_ai():
            return
        with st.status("Turning speech into text…", expanded=True) as status:
            st.write(f"Audio checked: {clock(length)} long. Sending it to {TRANSCRIBE_MODEL}…")
            try:
                cues = llm.transcribe_audio(backend(), filename, data)
            except llm.AIError as problem:
                state.runs += 1
                status.update(label="Couldn't turn the audio into text", state="error", expanded=False)
                st.error(str(problem))
                return
            state.runs += 1
            status.update(label="Speech turned into text", state="complete", expanded=False)
        state.transcriptions[digest] = cues
    try:
        transcript = from_cues(cues, [f"Transcribed from audio by {TRANSCRIBE_MODEL}. Chapter times come from "
                                      "its speech segments, so they are accurate to the start of a sentence or two."])
    except InputError as problem:
        st.warning(str(problem))
        return
    pack, seconds = make_pack(transcript)
    if pack is not None:
        save_result(pack, transcript, f"audio:{digest}", f"audio file {filename}", seconds, cached=False)


def ready_for_ai() -> bool:
    if runs_left() <= 0:
        st.warning(f"You've used all {MAX_RUNS_PER_SESSION} AI requests for this visit. "
                   "This keeps the shared free quota available for everyone.")
        return False
    if backend() is None:
        st.error("The app isn't set up with an AI key yet, so it can't generate anything.")
        return False
    return True


def make_pack(transcript: Transcript):
    """The one AI request that makes the overview, chapters and quiz. Returns (pack, seconds) or (None, None)."""
    if not ready_for_ai():
        return None, None
    with st.status("Working on it…", expanded=True) as status:
        st.write(f"Transcript checked: {transcript.word_count:,} words.")
        st.write(f"Asking the AI ({MODEL}). This usually takes a few seconds…")
        started = time.perf_counter()
        try:
            pack = llm.generate_study_pack(backend(), transcript.text, TranscriptIndex(transcript.text))
        except llm.AIError as problem:
            state.runs += 1
            status.update(label="Couldn't finish", state="error", expanded=False)
            st.error(str(problem))
            return None, None
        state.runs += 1
        st.write("Quotes checked against your transcript.")
        status.update(label="Done", state="complete", expanded=False)
    return pack, time.perf_counter() - started


def save_result(pack, transcript, marker, source, seconds, cached) -> None:
    """`marker` identifies the input, so the page can tell when the input has changed since."""
    state.result_id += 1
    state.result = {"pack": pack, "text": transcript.text, "transcript": transcript, "marker": marker,
                    "notices": transcript.notices,
                    "source": source, "seconds": seconds, "cached": cached,
                    "overviews": [("Original", pack.overview)], "quiz_checked": False}


def load_sample() -> None:
    state.transcript_text = SAMPLE_TEXT
    state.uploader_key += 1   # remove any uploaded file, otherwise it would be used instead of the sample


def queue_revision(label: str, request: str) -> None:
    state.pending_revision = (label, request)


def queue_custom_revision() -> None:
    text = state.get("custom_request", "").strip()
    queue_revision(f"Your request: {text[:40]}", text)


def undo_revision() -> None:
    if len(state.result["overviews"]) > 1:
        state.result["overviews"].pop()


def check_quiz() -> None:
    state.result["quiz_checked"] = True


def reset_quiz() -> None:
    state.result["quiz_checked"] = False
    for i in range(len(state.result["pack"].quiz)):
        state.pop(f"q{state.result_id}_{i}", None)


def run_pending_revision() -> None:
    label, request = state.pop("pending_revision")
    result = state.result
    if runs_left() <= 0:
        st.warning(f"You've used all {MAX_RUNS_PER_SESSION} AI requests for this visit.")
        return
    if backend() is None:
        st.error("The app isn't set up with an AI key yet.")
        return
    with st.spinner("Rewriting the overview…"):
        try:
            new = llm.revise_overview(backend(), result["text"], result["overviews"][-1][1], request)
        except InputError as problem:
            st.warning(str(problem))
            return
        except llm.AIError as problem:
            state.runs += 1
            st.error(str(problem))
            return
    state.runs += 1
    result["overviews"].append((label, new))


# ---------- results ----------

def show_trust(result) -> None:
    pack = result["pack"]
    if pack.quotes_verified == pack.quotes_total:
        st.success(f"✅ {trust_line(pack)} Open any chapter or quiz answer to see the exact words.")
    else:
        st.warning(f"⚠️ {trust_line(pack)} Items marked ⚠️ couldn't be checked, so treat them with care.")
    if pack.dropped_questions:
        st.caption(f"{pack.dropped_questions} broken quiz question(s) were removed before showing the quiz.")
    for notice in result["notices"]:
        st.info(notice)


def show_overview(result) -> None:
    if "pending_revision" in state:
        run_pending_revision()
    label, text = result["overviews"][-1]
    if len(result["overviews"]) > 1:
        st.caption(f"Revised ({label}). Version {len(result['overviews'])}.")
    st.write(text)

    st.markdown("**Not quite what you need? Change the overview**")
    st.caption("Only the overview is rewritten. Your chapters and quiz stay as they are.")
    columns = st.columns(len(REVISION_PRESETS))
    for column, (name, request) in zip(columns, REVISION_PRESETS.items()):
        column.button(name, on_click=queue_revision, args=(name, request), key=f"preset_{name}")
    st.text_input("Or describe the change", key="custom_request", max_chars=200,
                  placeholder="e.g. focus on the practical tips")
    left, right = st.columns(2)
    left.button("Rewrite", on_click=queue_custom_revision)
    right.button("Undo last change", on_click=undo_revision, disabled=len(result["overviews"]) < 2)


def show_chapters(result) -> None:
    pack, text, timing = result["pack"], result["text"], result["transcript"]
    if timing.has_times:
        st.caption("Times come from the timings in your input. Each one is the start of the line "
                   "where the chapter begins.")
    else:
        st.caption("No times are shown: this input has no timings, and the app never guesses them.")
    for i, (chapter, span) in enumerate(zip(pack.chapters, pack.chapter_spans(len(text))), start=1):
        flag = "" if chapter.check.verified else " ⚠️"
        when = timing.seconds_at(chapter.check.start) if chapter.check.verified else None
        at = f" · {clock(when)}" if when is not None else ""
        with st.expander(f"{i}. {chapter.title}{at}{flag}"):
            st.write(chapter.summary)
            if span is None:
                st.warning(f"This chapter's starting sentence wasn't found in the transcript "
                           f"({chapter.check.reason.lower()}), so it can't be opened.")
                st.caption(f"The AI said it starts with: “{chapter.start_quote}”")
                continue
            st.caption("This part of the transcript (its first sentence is highlighted):")
            with st.container(height=260):
                st.markdown(excerpt_html(text, span[0], span[1], chapter.check.start, chapter.check.end),
                            unsafe_allow_html=True)   # safe: excerpt_html escapes all transcript text


def show_quiz(result) -> None:
    pack, text, rid = result["pack"], result["text"], state.result_id
    timing = result["transcript"]
    checked = result["quiz_checked"]
    with st.form(f"quiz_{rid}"):
        for i, q in enumerate(pack.quiz):
            choice = st.radio(f"**{i + 1}. {q.question}**", options=list(range(len(q.options))), index=None,
                              key=f"q{rid}_{i}", format_func=lambda j, q=q: f"{LETTERS[j]}. {q.options[j]}")
            if checked:
                show_feedback(q, choice, text, timing)
        st.form_submit_button("Check my answers", type="primary", on_click=check_quiz)
    if checked:
        answers = [state.get(f"q{rid}_{i}") for i in range(len(pack.quiz))]
        score = sum(a == q.answer_index for a, q in zip(answers, pack.quiz))
        st.subheader(f"Score: {score} / {len(pack.quiz)}")
        st.button("Try the quiz again", on_click=reset_quiz)


def show_feedback(q, choice, text, timing) -> None:
    right = f"{LETTERS[q.answer_index]}. {q.options[q.answer_index]}"
    if choice is None:
        st.info(f"Not answered. The answer is {right}")
    elif choice == q.answer_index:
        st.success("Correct.")
    else:
        st.error(f"Not quite. The answer is {right}")
    st.caption(q.explanation)
    if q.check.verified:
        when = timing.seconds_at(q.check.start)
        if when is not None:
            st.caption(f"In the episode at {clock(when)}:")
        st.markdown(excerpt_html(text, q.check.start - 200, q.check.end + 200, q.check.start, q.check.end),
                    unsafe_allow_html=True)   # safe: excerpt_html escapes all transcript text
    else:
        st.warning(f"⚠️ The supporting quote wasn't found in the transcript, so check this answer yourself: "
                   f"“{q.evidence_quote}”")


def show_export(result) -> None:
    timing = result["transcript"]
    markdown = to_markdown(result["pack"], result["overviews"][-1][1], result["notices"],
                           timing.seconds_at if timing.has_times else None)
    st.download_button("Download as Markdown (.md)", markdown, file_name="podcast-study-pack.md",
                       mime="text/markdown", type="primary")
    st.caption("Or copy it with the button at the top right of the box below.")
    st.code(markdown, language="markdown")
    if result["marker"].startswith("audio:"):
        st.download_button("Download the transcript (.txt)", result["text"], file_name="transcript.txt",
                           mime="text/plain")


# ---------- page ----------

def show_intro() -> None:
    """What a first-time visitor needs to decide whether this is worth trying."""
    st.title("🎧 Podcast Companion")
    st.markdown("#### Remember what you listen to.")
    st.write("Paste an episode's transcript. In a few seconds you get the main ideas, chapters you can "
             "jump to, and a short quiz so it sticks. Every chapter and answer points to the exact words "
             "in the episode, so nothing is made up.")
    if state.result is None:
        for column, (icon, title, text) in zip(st.columns(3), [
                ("📝", "The gist", "A short overview you can make shorter, simpler or more detailed."),
                ("📍", "Chapters", "Each with a summary and the transcript part it covers, with times when the input has them."),
                ("🧠", "A quick quiz", "Five questions with answers, each backed by a quote from the episode.")]):
            with column.container(border=True):
                st.markdown(f"**{icon} {title}**")
                st.caption(text)


def episode_input():
    """The transcript box, the upload box and the buttons. Returns (raw text, source, uploaded file, is audio)."""
    st.text_area("Transcript", key="transcript_text", height=220,
                 placeholder="Paste the transcript here.")
    st.caption("Tip: on YouTube, click ...more under the video, then Show transcript. Copy all of it and paste "
               "it here. The times are kept, so chapters show when they start.")
    uploaded = st.file_uploader(
        "Or upload a file", type=UPLOAD_TYPES, key=f"upload_{state.uploader_key}",
        help=f"Text: .txt, or .srt/.vtt subtitles (their timings are kept). "
             f"Audio: .mp3, .m4a, .wav, .ogg or .flac, up to {MAX_AUDIO_MINUTES} minutes and 25 MB.")
    st.caption(f"Up to {MAX_TRANSCRIPT_WORDS:,} words per run (roughly 18 to 25 minutes of talk), or audio up to "
               f"{MAX_AUDIO_MINUTES} minutes. Only use episodes you have permission to use. What you send goes "
               "to Groq, an AI provider, to be processed. This app doesn't store it.")

    raw, source = state.get("transcript_text", ""), "pasted text"
    audio_upload = uploaded is not None and is_audio(uploaded.name)
    if audio_upload:
        st.audio(uploaded)
        st.caption(f"Using the audio file {uploaded.name} instead of the text box. "
                   "It uses 2 AI requests: one to turn speech into text, one for the study pack.")
    elif uploaded is not None:
        try:
            raw, source = read_upload(uploaded.name, uploaded.getvalue()), f"file {uploaded.name}"
            st.caption(f"Using the uploaded file {uploaded.name} instead of the text box.")
        except InputError as problem:
            st.warning(str(problem))
            raw = ""
    return raw, source, uploaded, audio_upload


def show_results(result, raw, uploaded, audio_upload) -> None:
    current = f"audio:{hashlib.sha256(uploaded.getvalue()).hexdigest()}" if audio_upload else raw.strip()
    if current and current != result["marker"]:
        st.info("The episode above has changed since these results were made. Generate again to update them.")
    pack = result["pack"]
    st.subheader("Your study pack")
    origin = ("Loaded from memory: no AI request used." if result["cached"]
              else f"Made in {result['seconds']:.1f} s.")
    st.caption(f"From {result['source']} · {result['transcript'].word_count:,} words · {len(pack.chapters)} chapters "
               f"· {len(pack.quiz)} quiz questions. {origin}")
    show_trust(result)
    tabs = st.tabs(["📝 Overview", "📍 Chapters", "🧠 Quiz", "⬇️ Save"], key="result_tabs")  # key: stay on the same tab after a click
    for tab, show in zip(tabs, [show_overview, show_chapters, show_quiz, show_export]):
        with tab:
            try:
                show(result)
            except Exception:   # a display bug in one tab must not break the others
                log.exception("Error while showing %s", show.__name__)
                st.error("This part couldn't be shown. The other tabs still work.")


show_intro()
result = state.result
# Before there are results, the episode box is open. After, it folds away so the results come first.
# The label must not change while results exist, or Streamlit would treat it as a new box and close it.
with st.expander("Your episode" if result is None else "Your episode · open to change it or try another one",
                 expanded=result is None):
    raw, source, uploaded, audio_upload = episode_input()
    word_count = len(raw.split())
    counter = st.empty()   # a placeholder: filled in at the very end of the page, so the number is never out of date
    left, right = st.columns([2, 1])
    clicked = left.button("Generate study pack", type="primary", disabled=not (raw.strip() or audio_upload),
                          width="stretch")
    right.button("Try a sample episode", on_click=load_sample, width="stretch",
                 help="A short invented episode about study techniques. It's free to try: its result is kept in memory.")
    made_before = state.result_id
    if clicked:
        try:
            if audio_upload:
                generate_from_audio(uploaded.name, uploaded.getvalue())
            else:
                generate(raw, source)
        except Exception:   # last safety net: log the details, show a calm message, never a traceback
            log.exception("Unexpected error while generating")
            st.error("Something unexpected went wrong. Please try again.")
if state.result_id != made_before:
    st.rerun()   # new results: draw the page again so they appear right under the folded episode box

if result:
    show_results(result, raw, uploaded, audio_upload)

st.divider()
with st.expander("How this works, and its limits"):
    st.markdown(f"""
- **AI:** {MODEL} on Groq's free plan. One request makes the overview, chapters and quiz together, usually in a few seconds.
- **Checking:** every chapter and quiz answer must quote the transcript. The app looks each quote up itself:
  at least {MIN_QUOTE_WORDS} words, the same words in the same order. The overview has no quote, so it isn't checked
  this way. Quiz options are shuffled by the app, and broken questions are removed.
- **Fresh each time:** generating again makes a new version, so chapters and questions can differ a little.
- **Audio:** turned into text by {TRANSCRIBE_MODEL} on Groq, then handled like a transcript. The length is read
  from the file first, so anything over {MAX_AUDIO_MINUTES} minutes is turned away before it is sent.
- **Limits:** up to {MAX_TRANSCRIPT_WORDS:,} words per run (roughly 18 to 25 minutes, depending on how fast people
  talk), and {MAX_RUNS_PER_SESSION} AI requests per visit, so the shared free quota lasts.
- **Timestamps:** shown only when the input has real timings: audio, .srt/.vtt files, or transcripts with times
  in them (such as a copied YouTube transcript). Plain text gets no times. The app never guesses them.
- **Privacy:** what you send goes to Groq to be processed and is not stored by this app. Zero Data Retention
  is switched on for this app's Groq account. Only the built-in sample's result is kept in memory.
- **Sleep:** the free host pauses the app after 12 hours without visitors, so the first load can be slow.
""")
st.caption("Made by Rafia Zarin Alisha · [Source code](https://github.com/rafiazarin/podcast-companion)")

# Filled last, so it also counts a revision made further down the page.
if audio_upload:
    counter.caption(f"Audio file · {runs_left()} AI requests left this visit")
else:
    counter.caption(f"{word_count:,} / {MAX_TRANSCRIPT_WORDS:,} words · {runs_left()} AI requests left this visit")
