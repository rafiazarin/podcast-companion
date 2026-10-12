"""Every setting a reviewer might ask me to change lives here, in one place."""

MODEL = "openai/gpt-oss-120b"   # chosen after the quote test (see probes/)
MAX_TRANSCRIPT_WORDS = 3500     # fits Groq's free 8,000 tokens per minute with room for the answer
MIN_QUOTE_WORDS = 6             # shorter quotes ("Interleaving.") prove nothing, so they don't count
MIN_TRANSCRIPT_WORDS = 150      # less than this is too little to summarise or quiz on
MAX_UPLOAD_BYTES = 200_000      # 3,500 words is about 20 KB, so this is generous
UPLOAD_TYPES = ["txt", "srt", "vtt"]
QUIZ_QUESTIONS = 5              # asked for in the prompt
MIN_QUIZ_QUESTIONS = 3          # fewer usable questions than this counts as a failed answer
MIN_CHAPTERS, MAX_CHAPTERS = 2, 8
REASONING_EFFORT = "low"        # less hidden thinking: fewer tokens and faster answers
TIMEOUT_SECONDS = 60            # give up on one AI call after this long
MAX_ATTEMPTS = 2                # one try plus one retry, so a bad run costs at most 2 requests
MAX_WAIT_SECONDS = 10           # wait out a short rate limit; tell the user about a long one
MAX_REVISION_CHARS = 200        # length limit for "how should I change the summary?"
MAX_RUNS_PER_SESSION = 12       # AI requests one visitor can trigger, to protect the shared daily quota
