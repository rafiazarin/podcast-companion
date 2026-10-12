import os
import time

from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
start = time.perf_counter()
response = client.models.generate_content(
    model="gemini-3.5-flash-lite",
    contents="Reply with exactly: hello from gemini",
)
print(response.text)
print(f"{time.perf_counter() - start:.2f} seconds")
