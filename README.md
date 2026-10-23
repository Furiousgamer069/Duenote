# 📒 DueNote

**Snap a photo of a handwritten dues notebook → get a clean ledger → send polite WhatsApp reminders in Urdu.**

Built at **Hacktoberfest Hack Day Faisalabad x Himmatkaar** with **Gemma 4**, Google's open-weight model.

## The problem

Millions of small shops in Pakistan run on a handwritten *khata* (credit notebook), and tuition academies track fees in paper registers. Owners lose money because they forget who owes what, and asking people for payment is awkward.

## What DueNote does

1. **Snap**: upload or take a photo of the notebook page (English, Urdu or Roman Urdu, messy handwriting is fine)
2. **Read**: Gemma 4 reads every entry: name, details, amount, and whether it was *owed* or *paid back*
3. **Check**: the owner can fix any misread line in an editable table
4. **Calculate**: **plain Python** works out each person's balance. The AI never does the maths, so it can't invent numbers
5. **Remind**: Gemma 4 writes a warm, respectful WhatsApp reminder for everyone who still owes money, in Urdu script or Roman Urdu, with a one-tap **Open in WhatsApp** button
6. **Export**: download the ledger as a CSV for Excel

Works in two modes: **🛒 Shop udhaar** and **🎓 Tuition fees**.

## How it works

```
Photo ──► Gemma 4 (vision) ──► entries table ──► owner edits ──► Python balances ──► Gemma 4 ──► WhatsApp reminders
```

- `khata.py`: core logic (Gemma calls, JSON parsing, balance maths, reminder writing)
- `app.py`: the Streamlit interface
- **Reliability**: if Google's servers are busy, DueNote retries and automatically switches between Gemma 4 models (`gemma-4-26b-a4b-it` → `gemma-4-31b-it`)

## 🧩 Agent skill: use DueNote inside any AI agent

DueNote also ships as an open **Agent Skill** following the `SKILL.md` standard: [`skills/duenote/SKILL.md`](skills/duenote/SKILL.md).

Drop the `skills/duenote` folder into any skill-compatible agent (Claude, Hermes Agent and others). The agent can then read a notebook photo, calculate balances, and draft Urdu WhatsApp reminders, following the same rule as the app: **the agent reads and writes, a script calculates.**

```bash
python skills/duenote/scripts/balances.py skills/duenote/scripts/example_entries.json
```

`balances.py` uses only the Python standard library, so it runs anywhere with no installs.

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add your free Gemini API key from https://aistudio.google.com/apikey, then:

```bash
streamlit run app.py
```

Click **"Try with a sample page"** to see it work instantly.

## What's next

- Voice notes in Urdu instead of photos
- Monthly reports and "who pays late" insights
- Running Gemma on the phone itself so shop data never leaves the device

## License

MIT, free and open source.
