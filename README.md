# Podcast Companion

Podcast Companion turns a podcast transcript or a short audio clip into an overview, chapters you can open, and a quiz. Every chapter and every quiz answer quotes the transcript, and the app checks each quote itself before showing it.

- Live app: https://podcast-companion-rafia.streamlit.app/
- Code: https://github.com/rafiazarin/podcast-companion

The app sleeps after 12 hours without visitors (a limit of the free host). If you see a wake-up button, click it and wait about a minute.

## What you can do with it

1. Give it an episode. Paste a transcript, upload a .txt, .srt or .vtt file, or upload audio (.mp3, .m4a, .wav, .ogg or .flac). You can also click "Try a sample episode" to try it straight away.
2. Read the overview. You can ask for a shorter version, simpler words, more detail, or describe your own change. Only the overview is rewritten, and you can undo a change.
3. Open the chapters. Each chapter opens to the part of the transcript it covers, with its first sentence highlighted.
4. Take the quiz. After you check your answers, each question shows the right answer, a short reason, and the sentence from the transcript that proves it.
5. Download or copy everything as Markdown. For audio, you can also download the transcript.

Above the results, the app shows how many quotes it found in the transcript, for example "10 of 10 quotes were found in the transcript".

## Limits

- Text: 150 to 3,500 words per run. That is roughly 18 to 25 minutes of speech, depending on how fast people talk. A real 20-minute YouTube clip I tested came to 3,757 words.
- Audio: up to 20 minutes and 25 MB.
- Each visit can make 12 AI requests. A text run uses 1 request, an audio run uses 2, and each overview change uses 1.
- Timestamps are shown only when the input has real timings: audio, .srt or .vtt files, or a pasted transcript with times in it (for example a transcript copied from YouTube). Plain text gets no times. The app never guesses them.
- The sample episode is a short invented conversation about study techniques, made for testing, so there are no permission issues with it.
- The real transcript in my tests and demo is from "10 reasons to study abroad - how it changed my life" by Katie Blake (https://www.youtube.com/watch?v=l7vFE14Onr0), shared on YouTube under a Creative Commons Attribution licence. It is not stored in this repo.

## Run it on your computer

You need Python 3.10 or newer (I used 3.12) and a free Groq API key from https://console.groq.com/keys.

```
git clone https://github.com/rafiazarin/podcast-companion.git
cd podcast-companion
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GROQ_API_KEY="your-key-here"
streamlit run app.py
```

The app opens at http://localhost:8501.

Instead of the export line, you can put the key in a file called `.streamlit/secrets.toml`:

```
GROQ_API_KEY = "your-key-here"
```

That file is listed in `.gitignore`, so it is never uploaded. On Streamlit Community Cloud, the key goes in the app's Secrets settings.

To run the tests (no API key or internet needed):

```
pip install -r requirements-dev.txt
python -m pytest -q
```

## How it works

The main idea is simple. The AI writes the content, but code decides what is true. The AI never decides where anything is in the transcript. It only returns text and quotes, and my code looks each quote up.

One run goes like this:

1. Check the input before any AI call. Empty text, too few or too many words, wrong file types, files that are not UTF-8, and audio over 20 minutes are all stopped here with a clear message, so they cost no quota.
2. For audio, turn speech into text with Whisper (whisper-large-v3-turbo on Groq). Each line keeps its start time.
3. Make the overview, chapters and quiz in one request to gpt-oss-120b on Groq. The answer must follow a fixed JSON shape (Groq's strict structured output).
4. Check the answer. Questions with a broken answer number or duplicate options are removed. The quiz options are shuffled in code, because in my tests the model almost always put the right answer in position B or C.
5. Look up every quote in the transcript. A quote only counts if it has at least 6 words and the same words in the same order as the transcript. Capitals, punctuation and extra spaces are ignored. Chapter starts are searched in order, so a phrase that appears twice can't put a chapter in the wrong place. Anything not found is marked as not verified instead of being hidden.
6. Show the results. Chapter text, highlights and times all come from the positions my code found, not from the AI.

The code is split so that only `app.py` uses Streamlit:

| File | What it does |
| --- | --- |
| `app.py` | The screen |
| `transcript.py` | Input checks, cleaning, and keeping real timings |
| `audio.py` | Audio checks, including reading the length before upload |
| `llm.py` | Groq calls, the timeout, retries and error messages |
| `prompts.py` | The instructions sent to the AI |
| `schemas.py` | The JSON shape and the checks on the AI's answer |
| `grounding.py` | The quote check |
| `formatting.py` | Transcript excerpts and the Markdown download |
| `config.py` | Every setting in one place (model, limits, quiz size) |

Because the logic has no Streamlit code in it, it could be moved behind an API later without changes.

## Comparing the AI providers

I compared two providers with free tiers: the Google Gemini API and Groq. My test scripts and their saved outputs are in the `probes` folder.

| | Gemini API (gemini-3.5-flash-lite) | Groq (openai/gpt-oss-120b) |
| --- | --- | --- |
| Fit for the task | Structured output supported. 1,048,576-token input, far more than any episode. | Strict structured output supported. 131,072-token context, but my free plan allows 8,000 tokens per minute, which caps one run at about 3,500 words. |
| Setting it up | About 5 lines for a first call. My first call failed with 403 PERMISSION_DENIED ("Your project has been denied access"). The key and code were fine. Other free-tier users report the same error on Google's forum, with no confirmed fix. | About 5 lines. It worked the first time. A rate limit returns 429 with a retry-after header, so the app can say how long to wait. |
| Output quality | Not tested, because the project was blocked. | On a 981-word sample: valid JSON, and 9 of 9 quotes found, all full sentences. |
| Speed and limits | Free limits are shown per project in AI Studio. I couldn't read mine before the block. | 3.3 seconds on the sample. Free plan: 30 requests per minute, 1,000 per day, 8,000 tokens per minute, 200,000 tokens per day. |
| Paid price per 1M tokens | $0.30 input, $2.50 output | $0.15 input, $0.60 output |
| Data | Free-tier content is used to improve Google's products. | My Groq console says inputs and outputs may be kept for up to 30 days unless you opt out. Groq's docs page says no retention by default, so the two disagree. I trusted the console and turned on Zero Data Retention. |

I also compared two Groq models on the same sample. gpt-oss-20b was faster (1.5 seconds against 3.3), but most of its chapter quotes were one to five words long, like "Interleaving.", which can't locate anything. gpt-oss-120b gave full sentences, so I chose it.

Why I chose Groq with gpt-oss-120b: it was the provider I could actually test, it returned the exact JSON shape every time, and its quotes worked with my checker. The cost is the 3,500-word limit per run on the free plan, which the app states clearly.

For the screen, I chose Streamlit on Streamlit Community Cloud over Gradio on Hugging Face Spaces (good for one input and one output, but awkward for a clickable quiz) and FastAPI with a separate frontend (more control, but two codebases, which was too much for the time I had).

Sources I used (all checked on 11 and 12 October 2026):

- Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing
- Gemini 3.5 Flash-Lite model page: https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- Gemini API rate limits: https://ai.google.dev/gemini-api/docs/rate-limits
- Gemini API available regions: https://ai.google.dev/gemini-api/docs/available-regions
- Google AI forum thread on the 403 error: https://discuss.ai.google.dev/t/gemini-api-403-permission-denied-your-project-has-been-denied-access-please-contact-support-error/170833
- Groq rate limits: https://console.groq.com/docs/rate-limits
- Groq structured outputs: https://console.groq.com/docs/structured-outputs
- Groq reasoning settings: https://console.groq.com/docs/reasoning
- Groq gpt-oss-120b model page and price: https://console.groq.com/docs/model/openai/gpt-oss-120b
- Groq speech to text: https://console.groq.com/docs/speech-to-text
- Groq data retention: https://console.groq.com/docs/your-data
- Streamlit Community Cloud deploy and app limits: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy and https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app
- Edison Research, The UK Podcast Consumer 2025 (for who listens to podcasts): https://www.edisonresearch.com/the-uk-podcast-consumer-2025/

## Debugging example: a quote check that passed but proved nothing

What went wrong. My first quote check only asked one question: does this quote appear in the transcript? I ran both Groq models on the sample. gpt-oss-20b scored 10 of 10, which looked perfect. When I read its actual answer, four of its five chapter quotes were one to five words long, such as "Interleaving." and "Highlighting." They do appear in the transcript, so they passed. But "Interleaving." appears in several places, so it can't show where a chapter starts.

How I investigated. I saved both models' full answers (they are in `probes`) and read them side by side instead of trusting the score. That also showed a second problem. In all 10 questions across both models, the right answer was option B or C, so a user could guess.

What I changed:

- A quote now needs at least 6 words to count.
- Chapter starts are searched in order, each one after the previous chapter.
- The prompt asks for full sentences of at least 8 words.
- Quiz options are shuffled in code, and the answer moves with them.
- I chose gpt-oss-120b, which gave full-sentence quotes.

I saved both real answers as test data. One test checks that the 20b answer's one-word quotes are now flagged. Another checks that the 120b answer passes with 9 of 9.

Result. Fixed for this case. In later runs of the full app, the sample got 10 of 10 quotes, all full sentences. What I learned: a passing score is not proof. Read the raw output.

Other problems I hit and fixed:

- Gemini blocked my project with a 403 error on the first call, so I switched providers (see the comparison above).
- After clicking "Check my answers", the page jumped back to the Overview tab. Giving the tabs a key made Streamlit remember the selected tab.
- The "AI requests left" counter was out of date after a revision, because it was drawn before the revision ran. It is now filled in at the end of the page.
- After testing audio, clicking "Load a sample episode" still used the uploaded audio, because an upload takes priority over the text box. Loading the sample now empties the upload box.

## Second debugging example: real YouTube transcripts

What went wrong. On the last morning I tested the live app with real transcripts copied from YouTube instead of my sample. A 20-minute clip was rejected at 4,322 words. When I cut it shorter, 0 of 10 quotes were found and the chapters showed no times, even though the text was full of them. A second video, copied in a different browser, got 1 of 11.

How I investigated. I ran my transcript reader on the exact text I had pasted and printed every time it found. In the first transcript, one caption line started with a time the speaker said out loud: "10:00 a.m. and going to sleep later." The reader took it as a timestamp, so the times seemed to jump to 10:00 and then back to 5:52. Because of that one line, it decided the whole thing wasn't a timed transcript. The times then stayed in the text as words, which split almost every quote and made the word count too high. The second video was copied in a different format. Each line had the time, then YouTube's hidden label for screen readers, glued to the words, like "1:041 minute, 4 secondsvery prepared". It also had chapter headings sitting in the middle of sentences.

What I changed:

- When most times sit on their own line, a time followed by words counts as speech. One time going backwards no longer cancels all the others.
- The hidden label is removed, but only when it says exactly the same time as the clock, so real speech is never cut.
- Chapter headings and sound labels like [Music] are taken out.
- After these fixes the second video got 5 of 10. Its captions were auto-generated, with no punctuation, and the AI was tidying the words in its quotes. The prompt now tells it to copy messy text exactly, filler words included.
- I added tests for each case with invented text in the same formats. The first one fails on the old code.

Result. The 20-minute clip is really 3,757 words, and its times are kept. The second video went from 1 of 11 to 10 of 10 quotes, with chapter times. What I learned: test with real, messy input early. My sample was too clean to show any of this.

## Reliability and what can still go wrong

How the app handles failures:

- Bad or broken AI answers. If the answer isn't valid JSON or has too few usable questions, the app retries once. If that fails too, it shows a plain message. Each AI step is tried at most twice, so a failing run can't drain the quota.
- Timeouts and connection drops. Each call stops after 60 seconds and is retried once.
- Rate limits. A short wait (10 seconds or less) is waited out. A longer one tells the user when to come back, using Groq's own wait time.
- A missing or wrong API key shows a message that it is a problem with the app, not the user's transcript.
- Unexpected errors are logged and shown as a calm message, never a raw error. If one tab fails to display, the others still work.
- Quota. The sample's result is kept in memory, so trying the sample is free. Each visit is capped at 12 AI requests. An audio file is turned into text only once per visit.

How I tested it:

- 90 automated tests. They cover the quote check, input checks, the answer checks, every failure type (using a fake AI that fails on purpose), and the real screen (using Streamlit's own test tool to type, click and read the page).
- Manual runs with the real AI: the sample got 10 of 10 quotes in 3.6 seconds. A one-minute test recording got 10 of 10 quotes, with the study pack made in 3.1 seconds.

Known limits:

- The overview has no quotes, so it isn't checked the way chapters and quiz answers are. The app says this on screen.
- A quote being found proves the words are in the transcript. It doesn't prove the explanation around it is right.
- For audio, quotes are checked against Whisper's text. If Whisper mishears a word, the check can't know.
- Long episodes have to be split by the user. The app doesn't split them itself yet.
- Each run can give slightly different chapters and questions. Every quote is still checked.
- The prompt tells the AI to treat the transcript as data and ignore instructions inside it. This lowers the risk of prompt injection but doesn't remove it.
- I tested two real YouTube copy formats. Transcripts copied from other sites may use formats the app doesn't read yet. Then it shows no times rather than wrong ones.
- The quote check handles Bangla script in the tests, but I haven't tested a full Bangla episode.

Security and privacy:

- The API key is only in an environment variable or Streamlit's secrets store, never in the code or the repo.
- The app doesn't store what users paste or upload. Only the sample's result is kept in memory.
- Zero Data Retention is turned on for the Groq account.
- Transcript text is escaped before it is shown, so text like `<script>` is displayed, never run.
- Uploads are limited by size and type, and Streamlit's usage statistics are turned off.

## Cost and maintenance

The live app runs on free tiers only (Groq's free plan and Streamlit Community Cloud), so it costs nothing to run now.

If it moved to Groq's paid plan, my estimate per run uses the sample's measured token counts (1,632 in, 1,150 out) and Groq's listed prices of $0.15 and $0.60. The model page doesn't print the unit, but its "6.7M / $1" note means per million tokens.

- Study pack: about $0.001 per run, so about $1 for 1,000 runs.
- Audio: Groq lists whisper-large-v3-turbo at $0.04 per hour of audio, so a 20-minute clip costs about $0.013.

These are estimates. Longer transcripts cost more, and prices can change.

Maintenance:

- Dependencies are pinned in `requirements.txt` (streamlit 1.65.0, groq 1.7.0, mutagen 1.48.1), so a new release can't break the live app by surprise.
- The model names and limits are in `config.py`. If Groq retires a model, the change is one line.
- Free-tier limits can change. The app reads Groq's wait time from each rate-limit response instead of assuming fixed numbers.
- The live app should be opened once before a demo, because the free host sleeps.

## Next steps

1. Handle full-length episodes. Split long transcripts into parts, make notes for each part, then combine them. This removes the 3,500-word limit, which is the biggest gap for real podcasts, since many episodes are an hour or more.
2. Measure quality on real episodes. Build a small test set of real transcripts, including messy auto-captions, and track the quote rate and quiz accuracy for each model and prompt change. Right now my numbers come from a few runs, and a test set would show whether a change really helps.
3. Keep working when the free quota runs out. Fall back to a second model or provider when Groq returns a rate limit, and show remaining capacity more clearly. With many users at once, the shared free quota is the most likely thing to fail.
