import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills" / "duenote" / "scripts"))

from extract import rows_to_entries  # noqa: E402
from ledger import (check_evidence, compute_balances, customer_id, format_rs, normalize_entry,  # noqa: E402
                    parse_amount, revision, suggest_aliases, total_due)
from store import Store, csv_safe  # noqa: E402


def load_fixture(name):
    result = json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))
    return rows_to_entries("p-test-" + name, result) + (result,)


def by_name(balances):
    return {c["name"]: c["balance"] for c in balances.values()}


# ---------- money parsing ----------
@pytest.mark.parametrize("raw, expected", [
    ("1,150", "1150.00"), ("۱۲۵۰", "1250.00"), ("١٢٥٠", "1250.00"), ("Rs. 3,550", "3550.00"),
    ("1,50,000", "150000.00"), ("750.5", "750.50"), (900, "900.00"), (12.25, "12.25"), ("٣٬٥٥٠", "3550.00"),
    ("2400/-", "2400.00"), ("0", "0.00"),
])
def test_parse_amount_valid(raw, expected):
    value, reason = parse_amount(raw)
    assert reason is None and value == Decimal(expected)


@pytest.mark.parametrize("raw", [None, "", "abc", "-500", "1,15", "12,34,5", "nan", "inf", float("nan"),
                                 float("inf"), True, "1.234", "5 0 0", "1,150,00"])
def test_parse_amount_invalid_stays_unknown(raw):
    value, reason = parse_amount(raw)
    assert value is None and reason


def test_unknown_values_are_unresolved_not_zero():
    e = normalize_entry({"name": "Ali", "amount": "??", "kind": "owed"})
    assert not e["resolved"] and e["amount"] is None and e["amount_raw"] == "??"
    b = compute_balances([e, normalize_entry({"name": "Ali", "amount": "100", "kind": "owed"})])
    assert b["ali"]["state"] == "needs checking" and b["ali"]["unresolved"] == 1


def test_ambiguous_direction_and_missing_fields():
    assert "direction unclear" in normalize_entry({"name": "A", "amount": "5", "kind": "maybe"})["reasons"][0]
    assert "name missing" in normalize_entry({"amount": "5", "kind": "owed"})["reasons"]


def test_decimal_partial_and_overpayment():
    entries = [normalize_entry(x) for x in [
        {"name": "A", "amount": "100.50", "kind": "owed"}, {"name": "A", "amount": "50.25", "kind": "paid"},
        {"name": "B", "amount": "100", "kind": "owed"}, {"name": "B", "amount": "150", "kind": "paid"},
        {"name": "C", "amount": "70", "kind": "owed"}, {"name": "C", "amount": "70", "kind": "paid"}]]
    b = compute_balances(entries)
    assert b["a"]["balance"] == Decimal("50.25") and b["a"]["state"] == "due"
    assert b["b"]["balance"] == Decimal("-50") and b["b"]["state"] == "credit"
    assert b["c"]["state"] == "settled"
    assert total_due(b) == Decimal("50.25") and format_rs(Decimal("50.25")) == "50.25"


# ---------- acceptance fixtures ----------
def test_roman_fixture_balances():
    entries, evidence, _ = load_fixture("roman_page.json")
    b = compute_balances(entries)
    assert by_name(b) == {"Usman": 3550, "Ali bhai": 400, "Bilal": 0}
    assert total_due(b) == 3950


def test_urdu_fixture_balances_keep_original_script_ids():
    entries, evidence, result = load_fixture("urdu_table.json")
    b = compute_balances(entries)
    assert by_name(b) == {"احمد علی": 7000, "عثمان": 4000, "عائشہ": 2500, "سارہ": 1200, "بلال خان": 0}
    assert total_due(b) == 14700
    assert "usman" not in b  # transliteration is not an identity
    assert check_evidence(b, evidence, result["written_total"]) == []  # page's own numbers agree


def test_written_balance_is_evidence_not_debt():
    result = {"rows": [{"row_ref": "1", "name": "X", "owed": "100", "paid": None, "written_balance": "999"}]}
    entries, evidence = rows_to_entries("p", result)
    assert len(entries) == 1 and evidence == {"X": "999"}
    warnings = check_evidence(compute_balances(entries), evidence, "50")
    assert any("page says 999" in w for w in warnings) and any("Page total" in w for w in warnings)


def test_payment_updates_total_exactly(tmp_path):
    entries, evidence, result = load_fixture("urdu_table.json")
    store = Store(str(tmp_path / "t.db"))
    assert store.save_page("p1", "Urdu", "summary", "shop", entries, evidence, "14700", "r1")
    store.record_payment("عثمان", "1,000", "23/10/2026", "cash")
    b = compute_balances(store.entries(), store.aliases())
    assert b["عثمان"]["balance"] == 3000 and total_due(b) == 13700
    # persists across restart
    b2 = compute_balances(Store(str(tmp_path / "t.db")).entries())
    assert total_due(b2) == 13700


@pytest.mark.parametrize("bad", ["0", "-5", "abc", ""])
def test_invalid_payments_rejected(bad):
    with pytest.raises(ValueError):
        Store().record_payment("Ali", bad)


def test_duplicate_import_idempotent_and_rephotograph_warned():
    entries, evidence, _ = load_fixture("roman_page.json")
    store = Store()
    assert store.save_page("p1", "a", "transactions", "shop", entries, evidence, None, "r")
    assert not store.save_page("p1", "a", "transactions", "shop", entries, evidence, None, "r")
    assert len(store.entries()) == len(entries)
    assert store.similar_page(entries)["id"] == "p1"  # same content, different photo -> warn


def test_unclear_rows_are_kept_pending_not_counted_then_fixed():
    store = Store()
    rows = [normalize_entry({"id": "1", "name": "A", "amount": "100", "kind": "owed"}),
            normalize_entry({"id": "2", "name": "Hina", "amount": "[unreadable]", "kind": ""})]
    assert store.save_page("p", "x", "transactions", "shop", rows, {}, None, "r")
    b = compute_balances(store.entries())
    assert total_due(b) == 100 and b["hina"]["state"] == "needs checking"
    with pytest.raises(ValueError):
        store.resolve_entry("2", "Hina", "still ??", "owed")  # invalid fix is refused
    store.resolve_entry("2", "Hina", "۷۵۰", "owed")
    b = compute_balances(store.entries())
    assert b["hina"]["balance"] == 750 and b["hina"]["state"] == "due" and total_due(b) == 850


# ---------- identity ----------
def test_names_never_auto_merge_but_aliases_can_be_approved():
    entries = [normalize_entry(x) for x in [
        {"name": "Ali", "amount": "100", "kind": "owed"}, {"name": "Ali bhai", "amount": "50", "kind": "owed"}]]
    assert len(compute_balances(entries)) == 2
    assert ("Ali", "Ali bhai") in suggest_aliases(["Ali", "Ali bhai"])
    store = Store()
    store.approve_alias("Ali bhai", "Ali")
    b = compute_balances(entries, store.aliases())
    assert len(b) == 1 and b["ali"]["balance"] == 150
    assert customer_id("ALI  BHAI", store.aliases()) == "ali"


def test_revision_changes_with_any_money_change():
    e1 = [normalize_entry({"id": "1", "name": "Ali", "amount": "900", "kind": "owed"})]
    e2 = [normalize_entry({"id": "1", "name": "Ali", "amount": "500", "kind": "owed"})]
    assert revision(e1) != revision(e2)
    assert revision(e1, context={"shop": "A"}) != revision(e1, context={"shop": "B"})


# ---------- skill and app agree ----------
def test_skill_cli_matches_app_on_example():
    script = ROOT / "skills" / "duenote" / "scripts"
    out = subprocess.run([sys.executable, str(script / "balances.py"), str(script / "example_entries.json")],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    assert "Total to collect: Rs. 3,950" in out
    rows = json.loads((script / "example_entries.json").read_text(encoding="utf-8"))
    assert total_due(compute_balances([normalize_entry(r) for r in rows])) == 3950


def test_review_edits_match_rows_by_id_after_deleting_a_middle_row():
    from extract import apply_edits
    entries, _, _ = load_fixture("roman_page.json")
    records = [{"id": e["id"], "name": e["name"], "amount": e["amount_raw"], "direction": e["kind"]} for e in entries]
    del records[1]  # owner deletes Bilal's first row
    out = apply_edits("p", entries, records)
    assert [e["original_text"] for e in out] == [e["original_text"] for e in entries if e is not entries[1]]
    assert out[1]["row_ref"] == "3" and "wapis diye" in out[1]["original_text"]


def test_export_of_unclear_row_has_blank_amount_not_none():
    from store import export_rows
    row = export_rows([normalize_entry({"name": "Hina", "amount": "[unreadable]", "kind": ""})])[0]
    assert row["amount"] == "" and row["type"] == "unclear" and row["status"].startswith("needs checking")
    assert row["written_as"] == "[unreadable]"


def test_csv_safe():
    assert csv_safe("=HYPERLINK(1)") == "'=HYPERLINK(1)" and csv_safe("@x") == "'@x" and csv_safe("Ali") == "Ali"
