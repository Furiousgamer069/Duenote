"""Measure live extraction against manually verified labels (the fixtures).

Run:  .venv/Scripts/python.exe eval/run_eval.py          # live Gemma calls (needs key + internet)
      .venv/Scripts/python.exe eval/run_eval.py --replay # pipeline check only, NOT a model measurement

Reports per page: rows matched / omitted / added, unresolved rows, balance accuracy, correction
effort (edits a person would need) and latency. Results are written to eval/results/.
"""
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "skills", "duenote", "scripts"))

from dotenv import load_dotenv  # noqa: E402

import images  # noqa: E402
from extract import extract_page, rows_to_entries  # noqa: E402
from ledger import compute_balances, name_key  # noqa: E402
from provider import GemmaProvider, ProviderError  # noqa: E402

LABELS = ["fixtures/roman_page.json", "fixtures/urdu_table.json"]


def keyset(entries, latin=False):
    return Counter((name_key(e["name_latin"] if latin else e["name"]), e["kind"], str(e["amount"]))
                   for e in entries if e["resolved"])


def score(expected, got):
    exp, out = keyset(expected), keyset(got)
    exp_l, out_l = keyset(expected, True), keyset(got, True)
    matched = sum((exp & out).values())
    eb = {k: c["balance"] for k, c in compute_balances(expected).items()}
    gb = {k: c["balance"] for k, c in compute_balances(got).items()}
    unresolved = sum(not e["resolved"] for e in got)
    omitted, added = sum((exp - out).values()), sum((out - exp).values())
    return {
        "expected_amounts": sum(exp.values()), "matched_exact": matched,
        "matched_ignoring_name_script": sum((exp_l & out_l).values()),
        "omitted": omitted, "added": added, "unresolved": unresolved,
        "balances_exact": sum(1 for k, v in eb.items() if gb.get(k) == v), "customers": len(eb),
        "correction_effort_edits": omitted + added + unresolved,
    }


def main():
    replay = "--replay" in sys.argv
    load_dotenv(os.path.join(ROOT, ".env"))
    provider = None if replay else GemmaProvider(overall_budget_s=300, race=True, max_attempts=6)  # as in app
    report = {"mode": "replay (pipeline check, not a model measurement)" if replay else "live",
              "when": datetime.now().isoformat(timespec="seconds"), "pages": []}
    for label_path in LABELS:
        label = json.load(open(os.path.join(ROOT, label_path), encoding="utf-8"))
        expected, _ = rows_to_entries("label", label)
        started = time.monotonic()
        try:
            if replay:
                result = label
            else:
                image, _ = images.load_photo(open(os.path.join(ROOT, label["image"]), "rb").read())
                result = extract_page(provider, images.for_model(image), "shop")
            got, _ = rows_to_entries("got", result)
            page = {"page": label["image"], "seconds": round(time.monotonic() - started, 1),
                    "model": getattr(provider, "last_model", None), **score(expected, got)}
        except (ProviderError, ValueError) as e:
            page = {"page": label["image"], "seconds": round(time.monotonic() - started, 1), "error": str(e)}
        report["pages"].append(page)
        print(json.dumps(page, ensure_ascii=False))
    os.makedirs(os.path.join(ROOT, "eval", "results"), exist_ok=True)
    out = os.path.join(ROOT, "eval", "results", f"{'replay' if replay else 'live'}-{datetime.now():%Y%m%d-%H%M}.json")
    json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("saved", out)


if __name__ == "__main__":
    main()
