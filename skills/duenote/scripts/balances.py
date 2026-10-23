"""Exact balance maths for the DueNote skill (standard library only).

Usage:  python balances.py entries.json
entries.json is a list of {"name", "amount", "type": "owed" | "paid", ...}
"""
import json
import sys


def compute(entries):
    totals = {}  # name -> [owed, paid], keeps first-seen order
    for e in entries:
        name = str(e.get("name") or "").strip()
        if not name:
            continue
        try:
            amount = float(str(e.get("amount", 0)).replace(",", "") or 0)
        except ValueError:
            amount = 0.0
        owed_paid = totals.setdefault(name, [0.0, 0.0])
        owed_paid[1 if e.get("type") == "paid" else 0] += amount
    rows = [{"name": n, "owed": o, "paid": p, "balance": o - p} for n, (o, p) in totals.items()]
    return sorted(rows, key=lambda r: r["balance"], reverse=True)


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python balances.py entries.json")
    with open(sys.argv[1], encoding="utf-8") as f:
        rows = compute(json.load(f))

    print(f"{'Name':<20}{'Owed':>10}{'Paid':>10}{'Balance':>10}")
    for r in rows:
        print(f"{r['name']:<20}{r['owed']:>10,.0f}{r['paid']:>10,.0f}{r['balance']:>10,.0f}")
    to_collect = sum(r["balance"] for r in rows if r["balance"] > 0)
    print(f"\nTotal to collect: Rs. {to_collect:,.0f}")


if __name__ == "__main__":
    main()
