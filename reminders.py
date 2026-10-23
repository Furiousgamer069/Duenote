"""Reminder drafts filled by code (no AI call), validated against the approved balance."""
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills", "duenote", "scripts"))
from ledger import format_rs, parse_amount, to_ascii_digits  # noqa: E402

TEMPLATES = {
    ("shop", "roman"): "Assalam-o-Alaikum {name}, umeed hai aap khairiyat se honge. {shop} ke khate mein "
                       "aapka baqaya Rs. {amount} hai. Jab suhoolat ho ada kar dijiye. Shukriya, {shop}.",
    ("shop", "urdu"): "السلام علیکم {name}، امید ہے آپ خیریت سے ہوں گے۔ {shop} کے کھاتے میں آپ کا بقایا "
                      "{amount} روپے ہے۔ سہولت کے مطابق ادا کر دیجیے۔ شکریہ، {shop}",
    ("fees", "roman"): "Assalam-o-Alaikum {name}, {shop} ki taraf se yaad-dehani: fees ka baqaya Rs. {amount} hai. "
                       "Suhoolat ke mutabiq jama karwa dijiye. Shukriya, {shop}.",
    ("fees", "urdu"): "السلام علیکم {name}، {shop} کی طرف سے یاد دہانی: فیس کا بقایا {amount} روپے ہے۔ "
                      "سہولت کے مطابق جمع کروا دیجیے۔ شکریہ، {shop}",
}


def draft(name, amount, shop, mode="shop", language="roman"):
    return TEMPLATES[(mode if mode in ("shop", "fees") else "shop", language)].format(
        name=name, shop=shop.strip() or "Shop", amount=format_rs(amount))


_MONEY = re.compile(r"(?<![\d/])(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{3,}(?:\.\d{1,2})?)(?![\d/])")


def check_draft(text, approved_amount):
    """The final message must state the approved amount and no other money figure."""
    found = [parse_amount(m)[0] for m in _MONEY.findall(to_ascii_digits(text))]
    found = [f for f in found if f is not None]
    if not found:
        return False, "The message doesn't mention the amount."
    wrong = [f for f in found if f != approved_amount]
    if wrong:
        return False, f"The message mentions Rs. {format_rs(wrong[0])}, but the approved balance is Rs. {format_rs(approved_amount)}."
    return True, ""


def normalize_phone(phone):
    """Pakistani mobile -> '923XXXXXXXXX'. Returns (number or '', error or None). Blank is allowed."""
    raw = (phone or "").strip()
    if not raw:
        return "", None
    digits = re.sub(r"[\s\-()]", "", to_ascii_digits(raw))
    if digits.startswith("+"):
        digits = digits[1:]
    elif digits.startswith("00"):
        digits = digits[2:]
    if re.fullmatch(r"03\d{9}", digits):
        digits = "92" + digits[1:]
    if re.fullmatch(r"923\d{9}", digits):
        return digits, None
    return "", "Use a Pakistani mobile number like 0300 1234567 or +92 300 1234567."


def display_phone(number):
    """'923001234567' -> '+92 300 1234567' (blank stays blank)."""
    if not number:
        return ""
    return f"+92 {number[2:5]} {number[5:]}" if len(number) == 12 and number.startswith("92") else number


def whatsapp_url(number, text):
    """Click-to-chat link. Opening WhatsApp is NOT the same as sending or being paid."""
    return f"https://wa.me/{number}?text={urllib.parse.quote(text)}"
