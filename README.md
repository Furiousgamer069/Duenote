# Khata Scanner

Turn a photo of a shopkeeper's handwritten credit notebook (*khata*) into a clean digital ledger, and get polite Urdu payment reminders for each customer.

Built with **Gemma 4** (open-weight model) via the Gemini API, for Hacktoberfest Hack Day Faisalabad x Himmatkaar (Oct 24, 2026).

> 🚧 Work in progress. The app itself is built during the hackathon.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add your Gemini API key from https://aistudio.google.com/apikey.

Check your setup:

```bash
python test_gemma.py samples/khata_sample.png
```

## License

MIT
