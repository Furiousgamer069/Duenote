"""DueNote: paper khata -> verified ledger -> respectful WhatsApp drafts -> payments -> history.

Run:  .venv/Scripts/streamlit.exe run app.py
"""
import html
import io
import json
import os
import sys
import time
from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "duenote", "scripts"))
load_dotenv(os.path.join(ROOT, ".env"))

import images  # noqa: E402
import reminders  # noqa: E402
from extract import apply_edits, extract_page, rows_to_entries  # noqa: E402
from ledger import (check_evidence, compute_balances, customer_id, format_rs, normalize_entry,  # noqa: E402
                    revision, suggest_aliases, total_due)
from provider import GemmaProvider, ProviderError  # noqa: E402
from store import Store, csv_safe, export_rows  # noqa: E402

SAMPLES = {
    "roman": ("Roman Urdu page", "samples/khata_sample.png", "fixtures/roman_page.json"),
    "urdu": ("Urdu table", "samples/real_page.png", "fixtures/urdu_table.json"),
}
STATE_BADGE = {"needs checking": "🟠 Needs checking", "due": "🔴 Due", "settled": "🟢 Settled", "credit": "🔵 Credit"}
KIND_LABELS = {"owed": "owed", "paid": "paid", "": "unclear"}

st.set_page_config(page_title="DueNote", page_icon="📒", layout="wide")
st.markdown("""<style>
.rtl {direction: rtl; text-align: right; font-size: 1.15rem; line-height: 1.9;}
div.stButton > button, a[data-testid="stLinkButton"] {min-height: 2.8rem;}
</style>""", unsafe_allow_html=True)


def rtl(text):
    st.markdown(f'<div class="rtl">{html.escape(str(text))}</div>', unsafe_allow_html=True)


# ---------------- session setup ----------------
ss = st.session_state
ss.setdefault("page", None)        # current capture (provisional, never shared between sessions)
ss.setdefault("drafts", {})        # customer_id -> draft bound to a ledger revision
ss.setdefault("demo_store", None)

with st.sidebar:
    st.header("⚙️ DueNote")
    data_mode = st.radio("Data", ["🧪 Demo (temporary)", "🏪 My shop (saved on this computer)"],
                         help="Demo data lives only in this browser session. My shop is saved to data/duenote.db.")
    nb_label = st.radio("Notebook type", ["🛒 Shop udhaar", "🎓 Tuition fees"])
    mode = "shop" if "Shop" in nb_label else "fees"
    business = st.text_input("Shop / academy name", "Bismillah General Store" if mode == "shop" else "Al-Noor Academy")
    st.divider()
    st.caption("Gemma 4 (open-weight, via Gemini API) only transcribes. Python does all the maths. "
               "Nothing is sent on WhatsApp automatically.")
    show_debug = st.toggle("Show technical details", False)

if data_mode.startswith("🧪"):
    if ss.demo_store is None:
        ss.demo_store = Store(":memory:")
    store = ss.demo_store
else:
    @st.cache_resource
    def shop_store():
        return Store(os.path.join(ROOT, "data", "duenote.db"))
    store = shop_store()


@st.cache_resource
def get_provider():
    # Ask both Gemma 4 models at once (first good answer wins); 6 tries each because Google's
    # free tier often returns quick 500s under load that succeed on a later try.
    return GemmaProvider(race=True, max_attempts=6)


READ_CACHE_SIZE = 8  # finished reads remembered per browser session (private, bounded)


def new_page(page_id, image, label, is_demo):
    """Any new photo fully replaces the previous capture, so old results can't leak onto it."""
    ss.page = {"page_id": page_id, "image": image, "label": label, "is_demo": is_demo, "rotation": 0,
               "result": None, "entries": None, "evidence": {}, "error": None, "seconds": None}


def load_extraction(result, seconds=None):
    page = ss.page
    entries, evidence = rows_to_entries(page["page_id"], result)
    page.update(result=result, entries=entries, evidence=evidence, error=None, seconds=seconds)


st.title("📒 DueNote")
st.caption("Paper khata → checked ledger → respectful WhatsApp drafts → record payments")

STEPS = ["1 · Capture · تصویر", "2 · Review · جانچ", "3 · Collect · وصولی", "4 · History · ریکارڈ"]
ss.setdefault("step", STEPS[0])


def go(i):
    ss.step = STEPS[i]  # runs as a button callback, before the step selector is drawn


def nav(i):
    """Back / Next buttons: you can always move to any step."""
    st.divider()
    b, n = st.columns(2)
    if i > 0:
        b.button(f"← {STEPS[i - 1]}", on_click=go, args=(i - 1,), width="stretch", key=f"back_{i}")
    if i < len(STEPS) - 1:
        n.button(f"{STEPS[i + 1]} →", on_click=go, args=(i + 1,), width="stretch", type="primary", key=f"next_{i}")


step = st.radio("Step", STEPS, key="step", horizontal=True, label_visibility="collapsed")
if ss.get("flash"):
    message = ss.pop("flash")  # feedback from the last action (payment, confirm, fix)
    st.success(message)
    st.toast(message)  # also visible when scrolled down on a phone

# ================= 1. CAPTURE =================
if step == STEPS[0]:
    st.subheader("Photograph a khata page")
    c1, c2 = st.columns(2)
    for col, key in ((c1, "roman"), (c2, "urdu")):
        title, img_path, _ = SAMPLES[key]
        if col.button(f"🧪 Sample replay: {title}", key=f"sample_{key}", width="stretch"):
            data = open(os.path.join(ROOT, img_path), "rb").read()
            image, pid = images.load_photo(data)
            new_page(pid, image, f"Sample: {title}", is_demo=key)
            ss.last_upload_id = None  # so uploading a photo again later still replaces the sample
    st.caption("Sample replay uses a manually verified transcription. **No AI call, no internet, no key.**")

    up_tab, cam_tab = st.tabs(["📁 Upload photo", "📷 Camera"])
    with up_tab:
        uploaded = st.file_uploader("Notebook page", type=["png", "jpg", "jpeg", "webp"], label_visibility="collapsed")
    with cam_tab:
        snapped = st.camera_input("Take a photo", label_visibility="collapsed")
    incoming = uploaded or snapped
    if incoming is not None:
        data = incoming.getvalue()
        upload_id = images.page_id_for(data)
        if ss.get("last_upload_id") != upload_id:  # only a NEW file replaces the current page
            ss.last_upload_id = upload_id
            try:
                image, pid = images.load_photo(data)
                new_page(pid, image, getattr(incoming, "name", "camera photo"), is_demo=None)
            except images.ImageProblem as e:
                ss.page = None
                st.error(f"⚠️ {e}")

    page = ss.page
    if page:
        left, right = st.columns([3, 2])
        with left:
            st.image(page["image"], caption=page["label"], width="stretch")
        with right:
            r1, r2 = st.columns(2)
            for col, deg, label in ((r1, -90, "↺ Rotate left"), (r2, 90, "↻ Rotate right")):
                if col.button(label, width="stretch"):
                    page["image"] = images.rotate(page["image"], deg)
                    page["rotation"] = (page["rotation"] + deg) % 360
                    page.update(result=None, entries=None, evidence={}, error=None)  # re-read after rotation
                    st.rerun()
            if page["is_demo"]:
                if st.button("▶️ Replay verified transcription", type="primary", width="stretch"):
                    fixture = json.load(open(os.path.join(ROOT, SAMPLES[page["is_demo"]][2]), encoding="utf-8"))
                    load_extraction(fixture)
            if st.button("🤖 Read with Gemma 4 (live AI)", type="secondary" if page["is_demo"] else "primary",
                         width="stretch"):
                started = time.monotonic()
                cache = ss.setdefault("read_cache", {})
                cache_key = f"{page['page_id']}:{page['rotation']}:{mode}"
                with st.status("Reading with Gemma 4 (live)…", expanded=True) as status:
                    try:
                        if cache_key in cache:
                            result = cache[cache_key]
                            st.write("Already read in this session. Reusing that result.")
                        else:
                            st.write("Asking both Gemma 4 models at once; the first good answer wins. "
                                     "Usually about 1 minute, longer when Google's servers are busy.")
                            result = extract_page(get_provider(), images.for_model(page["image"]), mode)
                            cache[cache_key] = result
                            while len(cache) > READ_CACHE_SIZE:
                                cache.pop(next(iter(cache)))  # drop the oldest
                        load_extraction(result, round(time.monotonic() - started))
                        status.update(label=f"Read in {page['seconds']} s", state="complete")
                    except ProviderError as e:
                        page.update(result=None, entries=None, evidence={}, error=e.friendly)
                        status.update(label="Couldn't read the page", state="error")
                    except ValueError as e:
                        page.update(result=None, entries=None, evidence={}, error=str(e))
                        status.update(label="Couldn't read the page", state="error")
            if page["error"]:
                st.error(f"⚠️ {page['error']} Nothing from earlier pages is shown for this photo.")
            if page["entries"] is not None:
                source = "Sample replay (verified demo data)" if page["is_demo"] and page["seconds"] is None \
                    else f"Live Gemma 4 read · {page['seconds']} s"
                st.success(f"✅ {len(page['entries'])} amounts found · {source}")
                st.button("Review this page →", on_click=go, args=(1,), type="primary", width="stretch",
                          key="review_now")
    nav(0)

# ================= 2. REVIEW =================
if step == STEPS[1]:
    page = ss.page
    if not page or page["entries"] is None:
        st.info("Capture and read a page first.")
    else:
        confirmed = store.has_page(page["page_id"])
        st.subheader("Check every row against the photo")
        if confirmed:
            st.info("✅ This page is already in your ledger, so the table is locked. "
                    "Fix any 🟠 rows or record payments in **3 · Collect**.")
        else:
            st.caption("Double-click a cell to edit. 🟠 = needs checking. Amounts accept 1,150 or ۱۲۵۰. "
                       "Nothing unreadable is counted as zero.")
        img_col, table_col = st.columns([2, 3])
        with img_col:
            st.image(page["image"], caption="Source page", width="stretch")
        with table_col:
            base = pd.DataFrame([{
                "id": e["id"], "row": e["row_ref"], "written": e["original_text"], "name": e["name"],
                "amount": e["amount_raw"], "direction": KIND_LABELS[e["kind"]],
                "check": "🟠 " + "; ".join(e["reasons"]) if e["reasons"] else "✅",
            } for e in page["entries"]])
            edited = st.data_editor(
                base, key=f"editor_{page['page_id']}", width="stretch", hide_index=True,
                num_rows="fixed" if confirmed else "dynamic",
                disabled=True if confirmed else ["id", "row", "written", "check"],
                column_order=["name", "amount", "direction", "check", "row", "written"],  # id stays hidden
                column_config={"direction": st.column_config.SelectboxColumn(options=["owed", "paid", "unclear"]),
                               "written": st.column_config.TextColumn(width="large")})
        provisional = apply_edits(page["page_id"], page["entries"], edited.to_dict("records"))

        unresolved = [e for e in provisional if not e["resolved"]]
        page_balances = compute_balances(provisional)
        warnings = check_evidence(page_balances, page["evidence"], (page["result"] or {}).get("written_total"))

        st.markdown("#### This page (provisional)")
        st.dataframe(pd.DataFrame([{"Name": c["name"], "Owed": format_rs(c["owed"]), "Paid": format_rs(c["paid"]),
                                    "Balance": format_rs(c["balance"]), "State": STATE_BADGE[c["state"]]}
                                   for c in page_balances.values()]), hide_index=True, width="stretch")
        if warnings:
            st.warning("**The page's own numbers disagree with the calculation:**\n\n- " + "\n- ".join(warnings))
        elif page["evidence"] or (page["result"] or {}).get("written_total"):
            st.success("✅ Balances and total written on the page match Python's calculation.")

        if unresolved and not confirmed:
            st.warning(f"🟠 {len(unresolved)} row(s) need checking. Fix them above now, or confirm anyway: "
                       "they'll be kept as **Needs checking**, not counted, and you can fix them in Collect.\n\n"
                       + "\n".join(f"- Row {e['row_ref']} ({e['name'] or '?'}): {'; '.join(e['reasons'])}"
                                   for e in unresolved))
        if not confirmed:
            similar = store.similar_page(provisional)
            if similar:
                st.warning(f"⚠️ This looks like the same page as '{similar['label']}' already in your ledger. "
                           "Confirm only if it's really a different page.")

            def confirm_page(page=page, rows=provisional):
                if store.save_page(page["page_id"], page["label"], (page["result"] or {}).get("page_kind"), mode,
                                   rows, page["evidence"], (page["result"] or {}).get("written_total"), revision(rows)):
                    pending = sum(not r["resolved"] for r in rows)
                    ss.flash = (f"✅ Page confirmed: {len(rows) - pending} rows added to your ledger."
                                + (f" {pending} kept as 🟠 Needs checking. Fix them below." if pending else ""))
                go(2)  # straight to Collect

            label = "✅ Confirm page into ledger · کھاتے میں شامل کریں"
            if unresolved:
                label = f"✅ Confirm {len(provisional) - len(unresolved)} clear rows · keep {len(unresolved)} for checking"
            st.button(label, type="primary", width="stretch", on_click=confirm_page)
    nav(1)

# ================= 3. COLLECT =================
if step == STEPS[2]:
    entries = store.entries()
    aliases = store.aliases()
    balances = compute_balances(entries, aliases)
    rev = revision(entries, aliases, {"business": business, "mode": mode})
    if not balances:
        st.info("Confirm a page in Review to build the ledger.")
    else:
        pending = [e for e in entries if not e["resolved"]]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total to collect", f"Rs. {format_rs(total_due(balances))}")
        m2.metric("Customers who owe", sum(c["state"] == "due" for c in balances.values()))
        m3.metric("Settled / credit", sum(c["state"] in ("settled", "credit") for c in balances.values()))
        m4.metric("Rows to check", len(pending))
        if pending:
            st.caption("🟠 Rows that need checking are **not counted** in any total, and those customers "
                       "get no reminder until you fix them.")

        def fix_form(e):
            """Owner fixes a pending row; it only counts once it's clear."""
            with st.form(f"fix_{e['id']}"):
                st.markdown(f"🟠 **Fix row {e['row_ref']}**: written `{e['original_text'] or e['amount_raw']}` · "
                            f"{'; '.join(e['reasons'])}")
                f1, f2, f3 = st.columns([3, 2, 2])
                name_in = f1.text_input("Name", e["name"])
                amount_in = f2.text_input("Amount (Rs.)", e["amount_raw"])
                kind_in = f3.selectbox("Direction", ["owed", "paid"],
                                       index=1 if e["kind"] == "paid" else 0)
                if st.form_submit_button("✔️ Save fix", width="stretch"):
                    try:
                        fixed = store.resolve_entry(e["id"], name_in, amount_in, kind_in)
                        ss.flash = f"✅ Row fixed: {fixed['name']} · Rs. {format_rs(fixed['amount'])} {fixed['kind']}."
                        st.rerun()
                    except ValueError as err:
                        st.error(str(err))

        nameless = [e for e in pending if not e["name"]]
        if nameless:
            with st.expander(f"🟠 {len(nameless)} row(s) with no name", expanded=True):
                for e in nameless:
                    fix_form(e)

        for a, b in suggest_aliases([e["name"] for e in entries], aliases):
            col_t, col_b = st.columns([4, 1])
            col_t.info(f"Are **{a}** and **{b}** the same person? DueNote never merges names by itself.")
            if col_b.button("Yes, same", key=f"alias_{a}_{b}"):
                store.approve_alias(b, a)
                ss.flash = f"✅ {b} and {a} are now one customer."
                st.rerun()

        for cid, c in balances.items():
            latin = next((e["name_latin"] for e in entries if e["name"] in c["names"] and e["name_latin"]), "")
            title = f"{c['name']}" + (f" ({latin})" if latin and latin != c["name"] else "")
            contact = store.contact(cid)
            # "Overdue" only when the owner saved a due date and it has passed
            overdue = c["state"] == "due" and contact["due_date"] and date.fromisoformat(contact["due_date"]) < date.today()
            badge = "⏰ Overdue" if overdue else STATE_BADGE[c["state"]]
            with st.expander(f"{badge} · **{title}** · Rs. {format_rs(c['balance'])}",
                             expanded=c["state"] in ("due", "needs checking")):
                st_rows = [e for e in entries if e["name"] and customer_id(e["name"], aliases) == cid]
                st.dataframe(pd.DataFrame([{"Date": e["date"], "Details": e["details"],
                                            "Type": e["kind"] or "🟠 unclear",
                                            "Amount": format_rs(e["amount"]) if e["amount"] is not None else "?",
                                            "Source": e["source"]} for e in st_rows]),
                             hide_index=True, width="stretch")
                for e in st_rows:
                    if not e["resolved"]:
                        fix_form(e)

                with st.form(f"pay_{cid}", clear_on_submit=True):
                    st.markdown("**Record payment · وصولی درج کریں**")
                    pc1, pc2, pc3 = st.columns([2, 2, 3])
                    amount_in = pc1.text_input("Amount (Rs.)", placeholder="1,000")
                    date_in = pc2.date_input("Date", value=date.today())
                    note_in = pc3.text_input("Note (optional)")
                    if st.form_submit_button("💰 Record payment", width="stretch"):
                        fingerprint = (cid, amount_in.strip(), date_in.isoformat(), note_in.strip())
                        last = ss.get("last_payment")
                        if last and last[0] == fingerprint and time.monotonic() - last[1] < 8:
                            # a double-tap re-sends the same form: never record the same payment twice
                            ss.flash = "ℹ️ That payment was already recorded (duplicate tap ignored)."
                            st.rerun()
                        try:
                            entry = store.record_payment(c["name"], amount_in, date_in.isoformat(), note_in)
                            ss.last_payment = (fingerprint, time.monotonic())
                            new_balance = c["balance"] - entry["amount"]
                            ss.flash = (f"✅ Recorded Rs. {format_rs(entry['amount'])} from {c['name']}. "
                                        + (f"New balance: Rs. {format_rs(new_balance)}." if new_balance >= 0 else
                                           f"They paid Rs. {format_rs(-new_balance)} more than they owed. "
                                           "This now shows as 🔵 Credit."))
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))

                if c["state"] == "needs checking":
                    st.info("📵 WhatsApp reminder unlocks once you fix the 🟠 rows above, "
                            "so we never ask for an uncertain amount.")
                if c["state"] != "due":
                    continue  # settled, credit and unchecked customers get no reminder

                st.markdown("**💬 WhatsApp reminder · یاد دہانی**")
                with st.form(f"contact_{cid}"):
                    k1, k2 = st.columns([3, 2])
                    phone_in = k1.text_input("WhatsApp number", reminders.display_phone(contact["phone"]),
                                             placeholder="03XX XXXXXXX or +92 3XX XXXXXXX")
                    due_in = k2.date_input("Due date (optional)", value=date.fromisoformat(contact["due_date"])
                                           if contact["due_date"] else None)
                    if st.form_submit_button("💾 Save number", width="stretch"):
                        number, phone_err = reminders.normalize_phone(phone_in)
                        if phone_err:
                            st.error(f"⚠️ {phone_err}")
                        else:
                            store.save_contact(cid, number, due_in.isoformat() if due_in else "")
                            ss.flash = (f"✅ Saved {reminders.display_phone(number)} for {c['name']}." if number
                                        else f"✅ Saved details for {c['name']} (no number).")
                            st.rerun()

                lang = st.radio("Message language", ["Roman Urdu", "اردو"], horizontal=True, key=f"lang_{cid}")
                lang_key = "roman" if lang == "Roman Urdu" else "urdu"
                draft = ss.drafts.get(cid)
                if draft and draft["revision"] != rev:
                    st.caption("🔄 The balance or shop details changed, so the message was rewritten "
                               f"with the current amount (Rs. {format_rs(c['balance'])}).")
                if draft is None or draft["revision"] != rev or draft["lang"] != lang_key:
                    # Always built from the CURRENT confirmed balance; any old wording is discarded
                    name_for_msg = c["name"] if lang_key == "urdu" else (latin or c["name"])
                    ss[f"msg_{cid}"] = reminders.draft(name_for_msg, c["balance"], business, mode, lang_key)
                    ss.drafts[cid] = draft = {"revision": rev, "lang": lang_key, "amount": c["balance"]}
                text = st.text_area("Preview: edit the wording if you like", key=f"msg_{cid}", height=110)
                if lang_key == "urdu":
                    rtl(text)
                ok, problem = reminders.check_draft(text, draft["amount"])
                if not ok:
                    st.error(f"⚠️ {problem} Fix the message to enable the button.")
                else:
                    number = contact["phone"]
                    label = (f"📲 Remind on WhatsApp ({reminders.display_phone(number)})" if number
                             else "📲 Remind on WhatsApp (choose contact)")
                    st.link_button(label, reminders.whatsapp_url(number, text), width="stretch", type="primary")
                    st.caption("Opens WhatsApp with this message ready. You press Send there. "
                               "Opening WhatsApp doesn't mean it was sent or paid.")
    nav(2)

# ================= 4. HISTORY =================
if step == STEPS[3]:
    st.subheader("Ledger history")
    pages, events = store.pages(), store.events()
    if pages:
        st.markdown("**Confirmed pages**")
        st.dataframe(pd.DataFrame([{"Page": p["label"], "Kind": p["page_kind"], "Confirmed": p["confirmed_at"],
                                    "ID": p["id"]} for p in pages]), hide_index=True, width="stretch")
    if events:
        st.markdown("**Events**")
        st.dataframe(pd.DataFrame([{"When": e["at"], "What": e["type"].replace("_", " "), "Customer": e["customer"],
                                    "Amount": e["amount"], "Note": e["note"]} for e in events]),
                     hide_index=True, width="stretch")
    entries = store.entries()
    if entries:
        tx = pd.DataFrame(export_rows(entries))
        summary = pd.DataFrame([{"name": csv_safe(c["name"]), "owed": str(c["owed"]), "paid": str(c["paid"]),
                                 "balance": str(c["balance"]), "state": c["state"]}
                                for c in compute_balances(entries, store.aliases()).values()])
        d1, d2 = st.columns(2)
        d1.download_button("⬇️ Transactions CSV", tx.to_csv(index=False).encode("utf-8-sig"),
                           "duenote_transactions.csv", "text/csv", width="stretch")
        d2.download_button("⬇️ Summary CSV", summary.to_csv(index=False).encode("utf-8-sig"),
                           "duenote_summary.csv", "text/csv", width="stretch")
    if not pages and not events:
        st.info("Nothing confirmed yet.")
    st.divider()
    if st.button("🗑️ Clear data in this mode", type="secondary"):
        store.clear()
        ss.page, ss.drafts, ss.read_cache = None, {}, {}
        st.rerun()
    nav(3)

if show_debug:
    with st.sidebar:
        st.json({"page_id": (ss.page or {}).get("page_id"), "drafts": list(ss.drafts),
                 "model": getattr(get_provider(), "last_model", None)})
