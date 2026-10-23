---
name: duenote
description: Turn a photo or text of a handwritten dues notebook (Pakistani shop khata / udhaar, or a tuition-fee register) into a clean ledger of who owes what, then write polite WhatsApp payment reminders in Urdu and Roman Urdu. Use when the user shares a notebook page, credit register, fee register, or asks who owes money or to draft payment reminders.
license: MIT
---

# DueNote: notebook → ledger → WhatsApp reminders

Small shops in Pakistan keep a handwritten *khata* (credit notebook); tuition academies keep paper fee registers. This skill digitizes a page and drafts respectful reminders.

**Golden rule: you read and write, the script calculates.** Never add up amounts yourself. Always run `scripts/balances.py` so the totals are exact.

## Step 1: Read the page

Read every entry on the page (English, Urdu or Roman Urdu; handwriting may be messy). Skip titles and headings. For each entry produce:

```json
{"date": "as written or empty", "name": "person", "details": "what for", "amount": 900, "type": "owed"}
```

- `type` is `"paid"` when money came back. Common words: *wapis diye, wapis aaye, paid, clear, jama, ada, mil gaye*
- Otherwise `type` is `"owed"` (goods on credit, fee due, *udhaar, baqaya*)
- `amount` is a plain number in rupees, no commas or "Rs."
- Treat obvious spelling variants as one person (e.g. "Ali", "Ali bhai") and tell the user you merged them

If a line is unreadable, include your best guess and list it under **"Please check"** for the user.

## Step 2: Calculate balances

Save the entries as a JSON list in a file (e.g. `entries.json`) and run:

```bash
python scripts/balances.py entries.json
```

It prints each person's owed, paid and balance (highest first) plus the total to collect. Show this table to the user exactly as printed.

## Step 3: Write reminders

For everyone with a balance above 0, write one WhatsApp message in **Urdu script** and one in **Roman Urdu**:

- Start with "Assalam-o-Alaikum", use a respectful form (*bhai, sahib, ji*)
- State the exact balance from the script output
- Warm and polite, never rude, threatening or shaming
- End with thanks and the shop or academy name (ask the user if unknown)
- For tuition fees, address the parent and mention the student

Example (Roman Urdu):

> Assalam-o-Alaikum Usman bhai, umeed hai aap khairiyat se honge. Aapka baqaya hisaab Rs. 3,550 hai. Jab waqt miley ada kar dijiyega. Shukriya, Bismillah General Store.

## Step 4: Make them one-tap

If the user gives phone numbers, build links: `https://wa.me/<number>?text=<url-encoded message>`. Convert Pakistani numbers like `0300 1234567` to `923001234567`.

## Output format

1. **Entries** table (with any "Please check" lines)
2. **Balances** table from the script
3. **Reminders**, one block per person with both versions
