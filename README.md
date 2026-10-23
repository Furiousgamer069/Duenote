# 📒 DueNote

**Turn a paper *khata* (credit notebook) into a checked collection ledger:**
photograph → check against the page → confirm balances → respectful WhatsApp draft → record payment → history.

Built at **Hacktoberfest Hack Day Faisalabad x Himmatkaar** with **Gemma 4** (Google's open-weight model, via the Gemini API). DueNote is a web app: it runs in the browser on a laptop or phone, with no install for the person using it.

## The problem

Small general stores in Pakistan give goods on credit (*udhaar*) and write it in a notebook. Totals get missed, people forget who owes what, and asking for money is awkward. DueNote helps the owner see exactly who owes what, checked against their own page, and send a polite reminder.

## How it works

| Step | What happens | Who does it |
|---|---|---|
| **1 · Capture** | Upload or snap a page (Urdu, Roman Urdu or English) | Owner |
| | Transcribe every row: name *as written*, amounts *as written*, owed or paid | **Gemma 4** (transcription only) |
| **2 · Review** | Photo and rows side by side; 🟠 rows need checking; written balances and totals compared with the calculation | Owner + Python |
| | **Confirm page.** Blocked until every row is clear | Owner |
| **3 · Collect** | Exact balances (Decimal), customer statements, **Record payment** | Python |
| | WhatsApp draft from a reviewed template; exact amount inserted by code; checked again after any edit | Python |
| **4 · History** | Confirmed pages, payment events, transaction and summary CSV exports | SQLite |

**Design rules**
- **The AI never does maths.** All money is parsed and summed in Python with `Decimal`.
- **Unknown is never zero.** `1,150`, `۱۲۵۰`, `١٢٥٠`, `Rs. 3,550`, `2400/-` are parsed exactly. Smudged, negative, missing or non-numeric amounts and unclear directions stay **unresolved** with a reason, and are excluded until the owner fixes them.
- **Written balances are evidence, not debts.** A page's "remaining" column and grand total are compared with the calculation, and any disagreement is shown.
- **Identity:** names are kept in the original script (`عثمان` ≠ `Usman`). Similar names are suggested, but **merged only when the owner approves**.
- **Drafts can't go stale.** Every draft is tied to a ledger revision (all amounts, aliases, shop name, mode). Change anything and the old draft disappears immediately.
- **Nothing is sent automatically.** "Open in WhatsApp" only opens click-to-chat with the draft. It doesn't mean the message was sent or the money paid.

## Run it (tested on Windows 11, Python 3.12)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501. On a phone on the same Wi-Fi, use the **Network URL** that Streamlit prints.

### Two modes
- **🧪 Sample replay (no key, no internet):** click *Sample replay → Replay verified transcription*. This loads a **manually verified transcription** of the sample page. It is **demo data, not live AI**.
- **🤖 Live AI:** copy `.env.example` to `.env`, add a free key from https://aistudio.google.com/apikey, then use *Read with Gemma 4 (live AI)* on any photo.

### Tests (no key, no network)

```bash
python -m pytest -q
```

78 tests: money parsing (Urdu/Arabic digits, lakh separators, decimals, negative/NaN/malformed), acceptance totals, the payment update, duplicate imports, aliases, draft invalidation, phone formats, malformed model JSON with one repair attempt, simulated 401/403/404/429/5xx/empty responses, corrupted and oversized uploads, EXIF rotation, CSV formula escaping, session isolation, and full app flows via Streamlit `AppTest`. CI runs them on every push (`.github/workflows/tests.yml`).

Live model check (uses your key): `python live_smoke_check.py`

## Acceptance results (automated tests)

| Check | Result |
|---|---|
| Roman Urdu sample: Usman 3,550 · Ali bhai 400 · Bilal 0 | **Rs. 3,950** in app *and* skill |
| Urdu table: احمد علی 7,000 · عائشہ 2,500 · بلال خان 0 · سارہ 1,200 · عثمان 4,000 | **Rs. 14,700**, matches the page's written total |
| Record عثمان's Rs. 1,000 payment | 3,000 → total **Rs. 13,700** (survives restart) |
| Edit / pay after drafting | old draft removed immediately |

## Measured live extraction (Gemma 4, 2 sample pages)

Measured on 23 Oct 2026, one run, model `gemma-4-26b-a4b-it`, compared against the manually verified fixtures:

| Page | Amounts found (exact name + type + amount) | Omitted / added rows | Unresolved | Balances exact | Correction edits | Latency |
|---|---|---|---|---|---|---|
| Roman Urdu (typed handwriting font) | 6 / 6 | 0 / 0 | 0 | 3 / 3 | 0 | 46.5 s |
| Urdu summary table (sample image) | 9 / 9 | 0 / 0 | 0 | 5 / 5 | 0 | 180.0 s |

On the Urdu page, names in Urdu script matched exactly. Two English transliterations differed from our labels (e.g. *Aisha* vs *Ayesha*), which is why identity uses the original script. Latency includes retries while Google's servers were busy.

### Speed work (measured, same day)

Token counts showed the image is cheap (~620 input tokens). The time goes on Gemma 4's hidden **thinking** (~4,000 tokens) before a ~760-token answer. The Gemini API rejects `thinking_budget` and `thinking_level` for Gemma, so we:

1. added a "simple copying task, answer directly" instruction to the prompt (Urdu page: thinking 4,008 → 2,478 tokens, **107 s → 75 s**, same correct result);
2. ask **both Gemma 4 models at once** and use the first valid answer, with more patient retries on Google's quick 500 errors;
3. remember finished reads per session, so re-reading the same photo is instant.

| After the changes | Time | Result |
|---|---|---|
| Urdu table | 66 s (was 180 s) | 9/9 amounts, 5/5 balances |
| Roman Urdu page | 55 s, during heavy server errors | 3/3 balances, Rs. 3,950 |

Reproduce: `python eval/run_eval.py` (live) · `python eval/run_eval.py --replay` (pipeline check only). Two pages is a tiny sample, so these numbers show the method, not general accuracy.

## Architecture

```
app.py            Streamlit UI: Capture / Review / Collect / History
extract.py        prompt, JSON schema validation, one bounded repair attempt, rows -> entries
provider.py       lazy Gemma adapter: configurable models, error classification, retries within a time budget
images.py         15 MB / 40 MP limits, corrupt-file handling, EXIF rotation, resize to 1600 px
reminders.py      Urdu + Roman Urdu templates, draft validation, Pakistani phone normalization
store.py          SQLite: confirmed pages, entries, payments, approved aliases, events; CSV-safe export
skills/duenote/   portable Agent Skill (SKILL.md) + scripts/ledger.py, the ONE money core shared with the app
fixtures/         manually verified transcriptions for Sample replay and evaluation labels
eval/             evaluation runner
tests/            pytest suite
```

**Model:** Gemma 4 (`gemma-4-26b-a4b-it`, fallback `gemma-4-31b-it`) through Google's Gemini API, set in `GEMMA_MODELS`. These IDs were listed by the Gemini API models endpoint for our key. We don't rely on structured-output parameters. Every response is validated against our own schema. Inference is **hosted by Google, not on-device**.

## 🧩 Agent skill

[`skills/duenote/SKILL.md`](skills/duenote/SKILL.md) teaches any skill-compatible agent the same workflow. `scripts/balances.py` uses the **same `ledger.py`** as the app (standard library only), so agents get identical results.

```bash
python skills/duenote/scripts/balances.py skills/duenote/scripts/example_entries.json
```

## Privacy

- **Demo mode** keeps data only in your browser session (in memory). It's gone when you close the tab.
- **My shop mode** stores confirmed data in `data/duenote.db` on *this computer* (excluded from Git). It's a **single-user prototype with no login**: don't host it publicly with real data. A typed shop name is not access control.
- Live AI sends the photo to Google's Gemini API. Notebook contents and keys aren't logged by DueNote. "Clear data" in History deletes the current mode's records.
- CSV exports escape text starting with `= + - @` to block spreadsheet formula injection.

## Status: what's real

| | |
|---|---|
| **Implemented** | Capture/Review/Collect/History, exact money core, unresolved handling, evidence checks, confirmation gate, payments, statements, aliases, revision-bound drafts, phone validation, SQLite history, CSV exports, agent skill, 78 tests, CI |
| **Replayed** | Sample replay uses verified fixtures. No AI runs in that mode |
| **Measured** | Live extraction on the 2 sample pages (above). No user testing yet |
| **Planned** | Crops of each source row, AI tone rewriting that keeps the amount locked, login for multi-user hosting, more labelled pages, voice input |

## Limitations

- Only 2 labelled pages, one of which is synthetic, so accuracy on real messy handwriting is not yet known.
- No per-row image crops: the full page is shown next to the rows instead (we don't invent boxes).
- Live reads take 1–3 minutes when Google's servers are busy.
- Summary pages and transaction pages for the same customer can double count; DueNote warns about re-photographed pages but can't detect every overlap.
- Single-user, local prototype. Not built for public multi-user hosting.

## License

MIT
