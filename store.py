"""SQLite storage for a single-user prototype: confirmed pages, payments, aliases, history.

Only CONFIRMED data is stored. Provisional extractions live in the browser session.
"""
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills", "duenote", "scripts"))
from ledger import PAID, name_key, normalize_entry, parse_amount  # noqa: E402

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id TEXT PRIMARY KEY, label TEXT, page_kind TEXT, mode TEXT, written_total TEXT,
    evidence TEXT, signature TEXT, revision TEXT, confirmed_at TEXT);
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY, page_id TEXT, row_ref TEXT, name TEXT, name_latin TEXT, date TEXT,
    details TEXT, original_text TEXT, amount_raw TEXT, amount TEXT, kind TEXT, source TEXT,
    created_at TEXT);
CREATE TABLE IF NOT EXISTS aliases (alias_key TEXT PRIMARY KEY, canonical_key TEXT, approved_at TEXT);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, type TEXT, customer TEXT, amount TEXT,
    note TEXT, ref TEXT);
"""


def _now():
    return datetime.now().isoformat(timespec="seconds")


def signature(entries):
    """Content fingerprint used to spot the same page photographed twice."""
    rows = sorted(f"{name_key(e['name'])}|{e['amount']}|{e['kind']}" for e in entries)
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16]


class Store:
    def __init__(self, path=":memory:"):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---- pages ----
    def has_page(self, page_id):
        return self.db.execute("SELECT 1 FROM pages WHERE id=?", (page_id,)).fetchone() is not None

    def similar_page(self, entries):
        row = self.db.execute("SELECT id, label FROM pages WHERE signature=?", (signature(entries),)).fetchone()
        return dict(row) if row else None

    def save_page(self, page_id, label, page_kind, mode, entries, evidence, written_total, revision):
        """Store a confirmed page. Same image again -> no change (idempotent). Returns True if saved."""
        if self.has_page(page_id):
            return False
        if any(not e["resolved"] for e in entries):
            raise ValueError("Resolve every row before confirming the page.")
        with self.db:
            self.db.execute(
                "INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?)",
                (page_id, label, page_kind, mode, written_total, json.dumps(evidence, ensure_ascii=False),
                 signature(entries), revision, _now()))
            for e in entries:
                self._insert_entry(e, page_id)
            self._event("page_confirmed", "", "", f"{len(entries)} rows", page_id)
        return True

    def pages(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM pages ORDER BY confirmed_at")]

    # ---- entries & payments ----
    def _insert_entry(self, e, page_id):
        self.db.execute(
            "INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (e["id"], page_id, e["row_ref"], e["name"], e["name_latin"], e["date"], e["details"],
             e["original_text"], e["amount_raw"], str(e["amount"]), e["kind"], e["source"], _now()))

    def entries(self):
        rows = self.db.execute("SELECT * FROM entries ORDER BY created_at, rowid")
        return [normalize_entry(dict(r), default_id=r["id"]) for r in rows]

    def record_payment(self, name, amount_raw, date="", note=""):
        """Validated payment -> traceable 'paid' entry + history event."""
        amount, reason = parse_amount(amount_raw)
        if amount is None:
            raise ValueError(f"Payment amount: {reason}")
        if amount == 0:
            raise ValueError("Payment amount must be more than 0.")
        if not str(name).strip():
            raise ValueError("Choose a customer.")
        n = self.db.execute("SELECT COUNT(*) FROM events WHERE type='payment'").fetchone()[0] + 1
        entry = normalize_entry({"name": name, "amount_raw": amount_raw, "kind": PAID, "date": date,
                                 "details": note or "payment recorded", "source": "payment"},
                                default_id=f"pay-{n}-{_now()}")
        with self.db:
            self._insert_entry(entry, "payments")
            self._event("payment", name, str(amount), note, entry["id"])
        return entry

    # ---- aliases (owner approved only) ----
    def aliases(self):
        return {r["alias_key"]: r["canonical_key"] for r in self.db.execute("SELECT * FROM aliases")}

    def approve_alias(self, alias_name, canonical_name):
        a, c = name_key(alias_name), name_key(canonical_name)
        if a == c:
            return
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO aliases VALUES (?,?,?)", (a, c, _now()))
            self._event("alias_approved", alias_name, "", f"same person as {canonical_name}", "")

    # ---- history ----
    def _event(self, type_, customer, amount, note, ref):
        self.db.execute("INSERT INTO events (at, type, customer, amount, note, ref) VALUES (?,?,?,?,?,?)",
                        (_now(), type_, customer, amount, note, ref))

    def events(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY id DESC")]

    def clear(self):
        with self.db:
            for table in ("pages", "entries", "aliases", "events"):
                self.db.execute(f"DELETE FROM {table}")


def csv_safe(value):
    """Stop spreadsheet formula injection: text starting with = + - @ is prefixed with '."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
