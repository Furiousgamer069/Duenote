"""DueNote ledger core: exact money parsing, entry validation and balances.

Standard library only, so the app and the portable agent skill share this one file.
Money is Decimal rupees with at most 2 decimal places. Nothing unreadable becomes zero:
it stays unresolved with a reason, and unresolved entries never count toward balances.
"""
import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation

OWED, PAID = "owed", "paid"
KINDS = (OWED, PAID)

# Urdu/Persian (U+06F0-06F9) and Arabic-Indic (U+0660-0669) digits -> ASCII
_DIGITS = {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_DIGITS.update({ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")})
_DIGITS.update({0x066C: ",", 0x066B: ".", 0x060C: ","})  # Arabic thousands/decimal separators

_CURRENCY = re.compile(r"^(rs\.?|pkr|₨|روپے|روپیہ|rupees?)\s*|\s*(rs\.?|pkr|₨|روپے|روپیہ|rupees?|/-)$", re.I)
# 1150 | 1,150 | 1,150,000 | lakh style 1,50,000 | optional .5 / .50
_WELL_FORMED = re.compile(r"^(\d+|\d{1,3}(,\d{3})+|\d{1,2}(,\d{2})+,\d{3})(\.\d{1,2})?$")
_HONORIFICS = {"bhai", "sahib", "sahab", "ji", "baji", "chacha", "uncle", "aunty", "mr", "mrs", "bhaijan"}


def to_ascii_digits(text):
    return str(text).translate(_DIGITS)


def parse_amount(raw):
    """Return (Decimal or None, reason or None). Never turns unknown money into zero."""
    if raw is None or isinstance(raw, bool):
        return None, "amount missing"
    if isinstance(raw, (int, float, Decimal)):
        text = repr(raw) if isinstance(raw, float) else str(raw)
    else:
        text = str(raw)
    text = to_ascii_digits(unicodedata.normalize("NFKC", text)).strip()
    if not text:
        return None, "amount missing"
    for _ in range(2):  # prefix and suffix
        text = _CURRENCY.sub("", text).strip()
    if text.startswith("-"):
        return None, "negative amount"
    if not _WELL_FORMED.match(text):
        return None, f"unreadable amount '{raw}'"
    try:
        value = Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None, f"unreadable amount '{raw}'"
    if not value.is_finite():
        return None, "amount is not a number"
    return value.quantize(Decimal("0.01")), None


def format_rs(value):
    """3550 -> '3,550'; 3550.5 -> '3,550.50'."""
    value = Decimal(value)
    if value == value.to_integral_value():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def name_key(name):
    """Exact identity key: Unicode-normalized, spacing collapsed, case-folded. No fuzzy matching."""
    text = unicodedata.normalize("NFKC", str(name or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _loose(name):
    words = [w for w in re.split(r"[\s.]+", name_key(name)) if w and w not in _HONORIFICS]
    return " ".join(words)


def normalize_entry(raw, default_id=None):
    """Validate one entry dict (from the model, the editor, or a payment). Keeps raw values."""
    name = str(raw.get("name") or "").strip()
    amount_raw = raw.get("amount_raw", raw.get("amount"))
    amount, reason = parse_amount(amount_raw)
    kind = str(raw.get("kind") or raw.get("type") or "").strip().lower()
    reasons = list(raw.get("reasons") or [])
    reasons = [r for r in reasons if not r.startswith(("amount", "negative", "unreadable", "direction", "name"))]
    if reason:
        reasons.append(reason)
    if kind not in KINDS:
        kind = ""
        reasons.append("direction unclear (owed or paid?)")
    if not name:
        reasons.append("name missing")
    return {
        "id": raw.get("id") or default_id,
        "page_id": raw.get("page_id"),
        "row_ref": str(raw.get("row_ref") or ""),
        "name": name,
        "name_latin": str(raw.get("name_latin") or "").strip(),
        "date": str(raw.get("date") or "").strip(),
        "details": str(raw.get("details") or "").strip(),
        "original_text": str(raw.get("original_text") or "").strip(),
        "amount_raw": "" if amount_raw is None else str(amount_raw),
        "amount": amount,
        "kind": kind,
        "source": raw.get("source") or "extracted",
        "reasons": reasons,
        "resolved": not reasons,
    }


def customer_id(name, aliases=None):
    """Customer ID = exact name key, redirected only through owner-approved aliases."""
    key = name_key(name)
    aliases = aliases or {}
    seen = set()
    while key in aliases and key not in seen:  # follow alias chains safely
        seen.add(key)
        key = aliases[key]
    return key


def compute_balances(entries, aliases=None):
    """Exact balances per customer from resolved entries only.

    Returns {customer_id: {...}} with owed, paid, balance, state and unresolved count.
    state: 'needs checking' | 'due' | 'settled' | 'credit'
    """
    out = {}
    for e in entries:
        if not e.get("name"):
            continue
        cid = customer_id(e["name"], aliases)
        c = out.setdefault(cid, {"customer_id": cid, "name": e["name"], "names": [],
                                 "owed": Decimal("0"), "paid": Decimal("0"), "unresolved": 0})
        if e["name"] not in c["names"]:
            c["names"].append(e["name"])
        if not e.get("resolved"):
            c["unresolved"] += 1
            continue
        c["owed" if e["kind"] == OWED else "paid"] += e["amount"]
    for c in out.values():
        c["balance"] = c["owed"] - c["paid"]
        if c["unresolved"]:
            c["state"] = "needs checking"
        elif c["balance"] > 0:
            c["state"] = "due"
        elif c["balance"] == 0:
            c["state"] = "settled"
        else:
            c["state"] = "credit"
    return dict(sorted(out.items(), key=lambda kv: kv[1]["balance"], reverse=True))


def total_due(balances):
    return sum((c["balance"] for c in balances.values() if c["balance"] > 0), Decimal("0"))


def check_evidence(balances, written_balances, written_total=None, aliases=None):
    """Compare balances written on the page with Python's maths. Returns warnings."""
    warnings = []
    for name, raw in (written_balances or {}).items():
        written, reason = parse_amount(raw)
        cid = customer_id(name, aliases)
        if written is None:
            warnings.append(f"{name}: written balance '{raw}' unreadable")
        elif cid in balances and balances[cid]["balance"] != written:
            warnings.append(f"{name}: page says {format_rs(written)}, calculated {format_rs(balances[cid]['balance'])}")
    if written_total not in (None, ""):
        written, reason = parse_amount(written_total)
        if written is None:
            warnings.append(f"Written total '{written_total}' unreadable")
        elif written != total_due(balances):
            warnings.append(f"Page total says {format_rs(written)}, calculated {format_rs(total_due(balances))}")
    return warnings


def suggest_aliases(names, aliases=None):
    """Possible same-person pairs for the OWNER to approve. Never merged automatically."""
    aliases = aliases or {}
    keys = {}
    for n in names:
        keys.setdefault(name_key(n), n)
    suggestions = []
    items = list(keys.items())
    for i, (ka, na) in enumerate(items):
        for kb, nb in items[i + 1:]:
            if customer_id(na, aliases) == customer_id(nb, aliases):
                continue
            la, lb = _loose(na), _loose(nb)
            if la and la == lb:
                suggestions.append((na, nb))
    return suggestions


def revision(entries, aliases=None, context=None):
    """Short fingerprint of everything that affects money. Any change -> new revision."""
    payload = {
        "entries": sorted(
            [str(e.get("id")), e["name"], str(e["amount"]), e["kind"], e["resolved"]] for e in entries
        ),
        "aliases": sorted((aliases or {}).items()),
        "context": context or {},
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, default=str).encode()).hexdigest()[:12]
