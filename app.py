"""The screen. Only this file uses Streamlit. All real logic lives in plain Python modules."""
import logging
import os
import time
from pathlib import Path

import streamlit as st

import llm
from config import MAX_RUNS_PER_SESSION, MAX_TRANSCRIPT_WORDS, MIN_QUOTE_WORDS, MODEL, UPLOAD_TYPES
from formatting import LETTERS, excerpt_html, to_markdown, trust_line
from grounding import TranscriptIndex
from transcript import InputError, prepare, read_upload

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


def runs_left() -> int:
    return MAX_RUNS_PER_SESSION - state.runs


# ---------- actions ----------

def generate(raw: str, source: str) -> None:
    try:
        transcript = prepare(raw)
    except InputError as problem:
        st.warning(str(problem))
        return

    is_sample = transcript.text == SAMPLE_TEXT.strip()
    store = sample_store()
    if is_sample and "pack" in store:
        save_result(store["pack"], transcript, raw, source, seconds=None, cached=True)
        return
    if runs_left() <= 0:
        st.warning(f"You've used all {MAX_RUNS_PER_SESSION} AI requests for this visit. "
                   "This keeps the shared free quota available for everyone.")
        return
    if backend() is None:
        st.error("The app isn't set up with an AI key yet, so it can't generate anything.")
        return

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
            return
        state.runs += 1
        seconds = time.perf_counter() - started
        st.write("Quotes checked against your transcript.")
        status.update(label="Done", state="complete", expanded=False)

    if is_sample:
        store["pack"] = pack
    save_result(pack, transcript, raw, source, seconds, cached=False)


def save_result(pack, transcript, raw, source, seconds, cached) -> None:
    state.result_id += 1
    state.result = {"pack": pack, "text": transcript.text, "raw": raw.strip(), "notices": transcript.notices,
                    "source": source, "seconds": seconds, "cached": cached,
                    "overviews": [("Original", pack.overview)], "quiz_checked": False}


def load_sample() -> None:
    state.transcript_text = SAMPLE_TEXT


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
        st.success(f"✅ {trust_line(pack)}")
    else:
        st.warning(f"⚠️ {trust_line(pack)} Items marked ⚠️ couldn't be checked, so treat them with care.")
    origin = ("Loaded from memory: no AI request used." if result["cached"]
              else f"Made by {MODEL} in {result['seconds']:.1f} s.")
    st.caption(f"{origin} Each chapter and quiz answer quotes the transcript, and the app looks every quote up "
               f"itself (at least {MIN_QUOTE_WORDS} words, same words in the same order). "
               "The overview has no quote, so it isn't checked this way.")
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

    st.markdown("**Change the overview**")
    st.caption("Only the overview is rewritten. The chapters and quiz stay as they are.")
    columns = st.columns(len(REVISION_PRESETS))
    for column, (name, request) in zip(columns, REVISION_PRESETS.items()):
        column.button(name, on_click=queue_revision, args=(name, request), key=f"preset_{name}")
    st.text_input("Or describe the change", key="custom_request", max_chars=200,
                  placeholder="e.g. focus on the practical tips")
    left, right = st.columns(2)
    left.button("Rewrite", on_click=queue_custom_revision)
    right.button("Undo last change", on_click=undo_revision, disabled=len(result["overviews"]) < 2)


def show_chapters(result) -> None:
    pack, text = result["pack"], result["text"]
    st.caption("Timestamps aren't shown: this version works from text only and never guesses times.")
    for i, (chapter, span) in enumerate(zip(pack.chapters, pack.chapter_spans(len(text))), start=1):
        flag = "" if chapter.check.verified else " ⚠️"
        with st.expander(f"{i}. {chapter.title}{flag}"):
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
    checked = result["quiz_checked"]
    with st.form(f"quiz_{rid}"):
        for i, q in enumerate(pack.quiz):
            choice = st.radio(f"**{i + 1}. {q.question}**", options=list(range(len(q.options))), index=None,
                              key=f"q{rid}_{i}", format_func=lambda j, q=q: f"{LETTERS[j]}. {q.options[j]}")
            if checked:
                show_feedback(q, choice, text)
        st.form_submit_button("Check my answers", type="primary", on_click=check_quiz)
    if checked:
        answers = [state.get(f"q{rid}_{i}") for i in range(len(pack.quiz))]
        score = sum(a == q.answer_index for a, q in zip(answers, pack.quiz))
        st.subheader(f"Score: {score} / {len(pack.quiz)}")
        st.button("Try the quiz again", on_click=reset_quiz)


def show_feedback(q, choice, text) -> None:
    right = f"{LETTERS[q.answer_index]}. {q.options[q.answer_index]}"
    if choice is None:
        st.info(f"Not answered. The answer is {right}")
    elif choice == q.answer_index:
        st.success("Correct.")
    else:
        st.error(f"Not quite. The answer is {right}")
    st.caption(q.explanation)
    if q.check.verified:
        st.markdown(excerpt_html(text, q.check.start - 200, q.check.end + 200, q.check.start, q.check.end),
                    unsafe_allow_html=True)   # safe: excerpt_html escapes all transcript text
    else:
        st.warning(f"⚠️ The supporting quote wasn't found in the transcript, so check this answer yourself: "
                   f"“{q.evidence_quote}”")


def show_export(result) -> None:
    markdown = to_markdown(result["pack"], result["overviews"][-1][1], result["notices"])
    st.download_button("Download as Markdown (.md)", markdown, file_name="podcast-study-pack.md",
                       mime="text/markdown", type="primary")
    st.caption("Or copy it with the button at the top right of the box below.")
    st.code(markdown, language="markdown")


# ---------- page ----------

st.title("🎧 Podcast Companion")
st.write("Paste a podcast transcript and get an overview, chapters you can open, and a quiz. "
         "Every quote is checked against your transcript.")
st.caption("Only use transcripts you have permission to use. The text is sent to Groq, an AI provider, "
           "to be processed. This app doesn't store what you paste.")

st.text_area("Transcript", key="transcript_text", height=220,
             placeholder="Paste the transcript here, or load the sample below.")
uploaded = st.file_uploader("Or upload a file", type=UPLOAD_TYPES,
                            help="Plain text, or .srt/.vtt subtitles (timings are removed).")
st.button("Load a sample episode", on_click=load_sample,
          help="A short invented episode about study techniques. It's free to try: its result is kept in memory.")

raw, source = state.get("transcript_text", ""), "pasted text"
if uploaded is not None:
    try:
        raw, source = read_upload(uploaded.name, uploaded.getvalue()), f"file {uploaded.name}"
        st.caption(f"Using the uploaded file {uploaded.name} instead of the text box.")
    except InputError as problem:
        st.warning(str(problem))
        raw = ""

word_count = len(raw.split())
counter = st.empty()   # a placeholder: filled in at the very end of the page, so the number is never out of date

if st.button("Generate study pack", type="primary", disabled=not raw.strip(), width="stretch"):
    try:
        generate(raw, source)
    except Exception:   # last safety net: log the details, show a calm message, never a traceback
        log.exception("Unexpected error while generating")
        st.error("Something unexpected went wrong. Please try again.")

result = state.result
if result:
    st.divider()
    if raw.strip() and raw.strip() != result["raw"]:
        st.info("The transcript above has changed since these results were made. Generate again to update them.")
    st.subheader("Your study pack")
    st.caption(f"From {result['source']}.")
    show_trust(result)
    for tab, show in zip(st.tabs(["Overview", "Chapters", "Quiz", "Export"], key="result_tabs"),  # key: stay on the same tab after a click
                         [show_overview, show_chapters, show_quiz, show_export]):
        with tab:
            try:
                show(result)
            except Exception:   # a display bug in one tab must not break the others
                log.exception("Error while showing %s", show.__name__)
                st.error("This part couldn't be shown. The other tabs still work.")

st.divider()
with st.expander("How this works, and its limits"):
    st.markdown(f"""
- **AI:** {MODEL} on Groq's free plan. One request makes the overview, chapters and quiz together.
- **Checking:** every chapter and quiz answer must quote the transcript. The app looks each quote up itself.
  Quotes under {MIN_QUOTE_WORDS} words don't count. Quiz options are shuffled by the app, and broken questions are removed.
- **Limits:** up to {MAX_TRANSCRIPT_WORDS:,} words per run (about 20 to 25 minutes of speech), and
  {MAX_RUNS_PER_SESSION} AI requests per visit, so the shared free quota lasts.
- **Timestamps:** not shown. This version works from text only and never guesses times.
- **Privacy:** what you paste is sent to Groq to be processed and is not stored by this app. Zero Data Retention
  is switched on for this app's Groq account. Only the built-in sample's result is kept in memory.
- **Sleep:** the free host pauses the app after 12 hours without visitors, so the first load can be slow.
""")
st.caption("Built by Rafia Zarin Alisha for the Thealon AI Engineering Challenge · "
           "[Source code](https://github.com/rafiazarin/podcast-companion)")

# Filled last, so it also counts a revision made further down the page.
counter.caption(f"{word_count:,} / {MAX_TRANSCRIPT_WORDS:,} words · {runs_left()} AI requests left this visit")
