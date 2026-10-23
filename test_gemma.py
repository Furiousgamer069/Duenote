"""Setup check: proves your API key works and Gemma can read an image.

Run:  .venv/Scripts/python.exe test_gemma.py [path-to-image]
"""
import os
import sys
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors
from PIL import Image

# Read GEMINI_API_KEY and GEMMA_MODEL from the .env file
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if not api_key or api_key == "paste-your-key-here":
    sys.exit("No API key found. Copy .env.example to .env and paste your key.")

client = genai.Client(api_key=api_key)

# Step 1: list the Gemma models your key can use
print("Gemma models available to you:")
gemma_models = [m.name for m in client.models.list() if "gemma" in m.name.lower()]
for name in gemma_models:
    print("  ", name)

model = os.getenv("GEMMA_MODEL")
if not model:
    sys.exit("\nPick a 'gemma-4' model from the list above and set GEMMA_MODEL in .env.")

# Step 2: send a text question, plus an image if one was given
contents = ["Describe what you see in one short sentence, then say it again in Urdu."]
if len(sys.argv) > 1:
    contents.append(Image.open(sys.argv[1]))
else:
    contents = ["Say hello to a hackathon participant in English and Urdu."]

# Step 3: ask, retrying on server errors and falling back to the other Gemma models
backups = [m.removeprefix("models/") for m in gemma_models if "gemma-4" in m and model not in m]
for candidate in [model] + backups:
    for attempt in range(1, 4):
        try:
            print(f"\nAsking {candidate} (attempt {attempt})...")
            response = client.models.generate_content(model=candidate, contents=contents)
            print(response.text)
            sys.exit(0)
        except errors.ServerError as e:
            # 500/503 mean Google's side is busy, so wait a bit longer each time
            print(f"  Server error {e.code}, retrying in {attempt * 5}s")
            time.sleep(attempt * 5)
sys.exit("\nAll Gemma models are busy right now. Try again in a few minutes.")
