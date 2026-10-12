"""Every setting a reviewer might ask me to change lives here, in one place."""

MODEL = "openai/gpt-oss-120b"   # chosen after the quote test (see probes/)
MAX_TRANSCRIPT_WORDS = 3500     # fits Groq's free 8,000 tokens per minute with room for the answer
MIN_QUOTE_WORDS = 6             # shorter quotes ("Interleaving.") prove nothing, so they don't count
