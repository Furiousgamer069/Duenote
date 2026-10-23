"""Core logic: Gemma 4 reads the notebook, Python does the maths, Gemma writes reminders."""
import json
import os
import re
import time

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import errors

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Fast model first, bigger one as backup when Google's servers are busy
MODELS = [os.getenv("GEMMA_MODEL") or "gemma-4-26b-a4b-it", "gemma-4-31b-it", "gemma-4-26b-a4b-it"]
MODELS = list(dict.fromkeys(MODELS))  # remove duplicates, keep order

MODES = {
    "shop": "a shopkeeper's credit notebook (khata / udhaar). Customers take goods on credit and pay later.",
    "fees": "a tuition academy's fee register. Students owe monthly fees and pay them later.",
}


def ask_gemma(contents):
    """Send a request to Gemma, retrying and switching models if the server is busy."""
    last_error = None
    for model in MODELS:
        for attempt in range(1, 3):
            try:
                return client.models.generate_content(model=model, contents=contents).text
            except errors.ServerError as e:
                last_error = e
                time.sleep(attempt * 3)
    raise RuntimeError(f"Gemma is busy right now, please try again. ({last_error})")


def parse_json(text):
    """Pull the JSON part out of Gemma's answer, even if it adds extra words around it."""
    text = re.sub(r"```(?:json)?", "", text)
    start = min([i for i in (text.find("["), text.find("{")) if i != -1], default=-1)
    end = max(text.rfind("]"), text.rfind("}"))
    if start == -1 or end == -1:
        raise ValueError("Gemma did not return a table. Try a clearer photo.")
    return json.loads(text[start : end + 1])


def read_notebook(image, mode="shop"):
    """Step 1 (AI reads): turn a notebook photo into a table of entries."""
    prompt = f"""This photo shows {MODES[mode]}
Entries may be in English, Urdu or Roman Urdu, and the handwriting may be messy.

Read EVERY entry and return ONLY a JSON list, no other text. Each item:
{{"date": "as written, or empty", "name": "person's name", "details": "what it was for",
  "amount": number in rupees, "type": "owed" or "paid"}}

Use "paid" when money was paid back (e.g. "wapis diye", "paid", "clear", "jama", "ada").
Otherwise use "owed". Skip titles and headings. Do NOT calculate totals."""
    rows = parse_json(ask_gemma([prompt, image]))
    df = pd.DataFrame(rows, columns=["date", "name", "details", "amount", "type"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    df["type"] = df["type"].where(df["type"].isin(["owed", "paid"]), "owed")
    return df


def compute_balances(entries):
    """Step 2 (code calculates): who owes how much. The AI never does the maths."""
    df = entries.copy()
    df["name"] = df["name"].fillna("").astype(str).str.strip()
    df = df[df["name"] != ""]
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    df["signed"] = df["amount"].where(df["type"] == "owed", -df["amount"])
    out = (
        df.groupby("name", sort=False)
        .agg(owed=("signed", lambda s: s[s > 0].sum()), paid=("signed", lambda s: -s[s < 0].sum()))
        .reset_index()
    )
    out["balance"] = out["owed"] - out["paid"]
    return out.sort_values("balance", ascending=False).reset_index(drop=True)


def write_reminders(balances, business_name, mode="shop"):
    """Step 3 (AI writes): polite WhatsApp reminders for everyone who still owes money."""
    due = balances[balances["balance"] > 0]
    if due.empty:
        return {}
    people = [{"name": r.name, "amount": int(r.balance)} for r in due.itertuples()]
    who = "customer of the shop" if mode == "shop" else "parent of a student at the academy"
    prompt = f"""Write a short, polite, respectful WhatsApp payment reminder for each person below.
Each person is a {who} "{business_name}". Pakistani context: warm, never rude or threatening.
Start with "Assalam-o-Alaikum", mention the exact amount in rupees, end with thanks and "{business_name}".

People: {json.dumps(people, ensure_ascii=False)}

Return ONLY a JSON list, no other text:
[{{"name": "...", "urdu": "message in Urdu script", "roman": "same message in Roman Urdu"}}]"""
    items = parse_json(ask_gemma([prompt]))
    return {item["name"]: item for item in items if "name" in item}
