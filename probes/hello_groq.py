import time

from groq import Groq

client = Groq()  # reads the key from the GROQ_API_KEY environment variable

for model in ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]:
    start = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply with exactly: hello from groq"}],
    )
    print(model, "->", response.choices[0].message.content)
    print(f"{time.perf_counter() - start:.2f} seconds")
