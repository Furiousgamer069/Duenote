"""Exact balance maths for the DueNote skill. Uses the shared ledger core (standard library only).

Usage:  python balances.py entries.json
entries.json is a list of {"name", "amount", "type": "owed" | "paid", ...}
Unreadable amounts or unclear directions are listed under "Needs checking", never counted as zero.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ledger import compute_balances, format_rs, normalize_entry, total_due  # noqa: E402


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python balances.py entries.json")
    with open(sys.argv[1], encoding="utf-8") as f:
        entries = [normalize_entry(e, default_id=str(i)) for i, e in enumerate(json.load(f), 1)]
    balances = compute_balances(entries)

    print(f"{'Name':<20}{'Owed':>10}{'Paid':>10}{'Balance':>10}  State")
    for c in balances.values():
        print(f"{c['name']:<20}{format_rs(c['owed']):>10}{format_rs(c['paid']):>10}{format_rs(c['balance']):>10}  {c['state']}")
    unresolved = [e for e in entries if not e["resolved"]]
    if unresolved:
        print("\nNeeds checking (not counted):")
        for e in unresolved:
            print(f"  row {e['id']}: {e['name'] or '?'} | {e['amount_raw']} | {', '.join(e['reasons'])}")
    print(f"\nTotal to collect: Rs. {format_rs(total_due(balances))}")


if __name__ == "__main__":
    main()
