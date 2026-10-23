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
from extract import extract_page, rows_to_entries  # noqa: E402
from ledger import (check_evidence, compute_balances, customer_id, format_rs, normalize_entry,  # noqa: E402
                    revision, suggest_aliases, total_due)
from provider import GemmaProvider, ProviderError  # noqa: E402
from store import Store, csv_safe  # noqa: E402

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

tab_capture, tab_review, tab_collect, tab_history = st.tabs(
    ["1 · Capture · تصویر", "2 · Review · جانچ", "3 · Collect · وصولی", "4 · History · ریکارڈ"])

# ================= 1. CAPTURE =================
with tab_capture:
    st.subheader("Photograph a khata page")
    c1, c2 = st.columns(2)
    for col, key in ((c1, "roman"), (c2, "urdu")):
        title, img_path, _ = SAMPLES[key]
        if col.button(f"🧪 Sample replay: {title}", key=f"sample_{key}", width="stretch"):
            data = open(os.path.join(ROOT, img_path), "rb").read()
            image, pid = images.load_photo(data)
            new_page(pid, image, f"Sample: {title}", is_demo=key)
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
                st.success(f"✅ {len(page['entries'])} amounts found · {source}\n\n➡️ Open **2 · Review**.")

# ================= 2. REVIEW =================
with tab_review:
    page = ss.page
    if not page or page["entries"] is None:
        st.info("Capture and read a page first.")
    else:
        st.subheader("Check every row against the photo")
        st.caption("🟠 = needs checking. Fix the amount or direction until every row is clear. "
                   "Amounts accept 1,150 or ۱۲۵۰. Nothing unreadable is counted as zero.")
        img_col, table_col = st.columns([2, 3])
        with img_col:
            st.image(page["image"], caption="Source page", width="stretch")
        with table_col:
            base = pd.DataFrame([{
                "row": e["row_ref"], "written": e["original_text"], "name": e["name"],
                "amount": e["amount_raw"], "direction": KIND_LABELS[e["kind"]],
                "check": "🟠 " + "; ".join(e["reasons"]) if e["reasons"] else "✅",
            } for e in page["entries"]])
            edited = st.data_editor(
                base, key=f"editor_{page['page_id']}", width="stretch", hide_index=True, num_rows="dynamic",
                disabled=["row", "written", "check"],
                column_order=["name", "amount", "direction", "check", "row", "written"],
                column_config={"direction": st.column_config.SelectboxColumn(options=["owed", "paid", "unclear"]),
                               "written": st.column_config.TextColumn(width="large")})
        provisional = []
        for i, row in enumerate(edited.to_dict("records")):
            original = page["entries"][i] if i < len(page["entries"]) else {}
            kind = {"owed": "owed", "paid": "paid"}.get(str(row.get("direction") or ""), "")
            provisional.append(normalize_entry({
                **original, "name": row.get("name"), "amount_raw": row.get("amount"), "kind": kind,
                "source": original.get("source", "manual"), "page_id": page["page_id"],
                "row_ref": row.get("row") or f"m{i + 1}"}, default_id=original.get("id") or f"{page['page_id']}:m{i + 1}"))

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

        if unresolved:
            st.error(f"🟠 {len(unresolved)} row(s) need checking before you can confirm:\n\n" + "\n".join(
                f"- Row {e['row_ref']} ({e['name'] or '?'}): {'; '.join(e['reasons'])}" for e in unresolved))
        elif store.has_page(page["page_id"]):
            st.info("This exact photo is already confirmed in your ledger (no double counting).")
        else:
            similar = store.similar_page(provisional)
            if similar:
                st.warning(f"⚠️ This looks like the same page as '{similar['label']}' already in your ledger. "
                           "Confirm only if it's really a different page.")
            if st.button("✅ Confirm page into ledger · کھاتے میں شامل کریں", type="primary", width="stretch"):
                store.save_page(page["page_id"], page["label"], (page["result"] or {}).get("page_kind"), mode,
                                provisional, page["evidence"], (page["result"] or {}).get("written_total"),
                                revision(provisional))
                st.success("Confirmed. ➡️ Open **3 · Collect**.")
                st.rerun()

# ================= 3. COLLECT =================
with tab_collect:
    entries = store.entries()
    aliases = store.aliases()
    balances = compute_balances(entries, aliases)
    rev = revision(entries, aliases, {"business": business, "mode": mode})
    if not balances:
        st.info("Confirm a page in Review to build the ledger.")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Total to collect", f"Rs. {format_rs(total_due(balances))}")
        m2.metric("Customers who owe", sum(c["state"] == "due" for c in balances.values()))
        m3.metric("Settled / credit", sum(c["state"] in ("settled", "credit") for c in balances.values()))

        for a, b in suggest_aliases([e["name"] for e in entries], aliases):
            col_t, col_b = st.columns([4, 1])
            col_t.info(f"Are **{a}** and **{b}** the same person? DueNote never merges names by itself.")
            if col_b.button("Yes, same", key=f"alias_{a}_{b}"):
                store.approve_alias(b, a)
                st.rerun()

        for cid, c in balances.items():
            latin = next((e["name_latin"] for e in entries if e["name"] in c["names"] and e["name_latin"]), "")
            title = f"{c['name']}" + (f" ({latin})" if latin and latin != c["name"] else "")
            with st.expander(f"{STATE_BADGE[c['state']]} · **{title}** · Rs. {format_rs(c['balance'])}",
                             expanded=c["state"] == "due"):
                st_rows = [e for e in entries if e["name"] and customer_id(e["name"], aliases) == cid]
                st.dataframe(pd.DataFrame([{"Date": e["date"], "Details": e["details"], "Type": e["kind"],
                                            "Amount": format_rs(e["amount"]) if e["amount"] is not None else "?",
                                            "Source": e["source"]} for e in st_rows]),
                             hide_index=True, width="stretch")

                with st.form(f"pay_{cid}", clear_on_submit=True):
                    st.markdown("**Record payment · وصولی درج کریں**")
                    pc1, pc2, pc3 = st.columns([2, 2, 3])
                    amount_in = pc1.text_input("Amount (Rs.)", placeholder="1,000")
                    date_in = pc2.date_input("Date", value=date.today())
                    note_in = pc3.text_input("Note (optional)")
                    if st.form_submit_button("💰 Record payment", width="stretch"):
                        try:
                            store.record_payment(c["name"], amount_in, date_in.isoformat(), note_in)
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))

                if c["state"] != "due":
                    continue
                st.markdown("**WhatsApp reminder**")
                lang = st.radio("Language", ["Roman Urdu", "اردو"], horizontal=True, key=f"lang_{cid}")
                lang_key = "roman" if lang == "Roman Urdu" else "urdu"
                draft = ss.drafts.get(cid)
                if draft and (draft["revision"] != rev or draft["lang"] != lang_key):
                    ss.drafts.pop(cid)  # ledger, shop, mode or language changed: old draft is void
                    ss.pop(f"msg_{cid}", None)
                    draft = None
                if draft is None:
                    if st.button("✍️ Prepare draft", key=f"prep_{cid}"):
                        name_for_msg = c["name"] if lang_key == "urdu" else (latin or c["name"])
                        text = reminders.draft(name_for_msg, c["balance"], business, mode, lang_key)
                        ss.drafts[cid] = {"revision": rev, "lang": lang_key, "amount": c["balance"]}
                        ss[f"msg_{cid}"] = text
                        st.rerun()
                else:
                    text = st.text_area("Message (you can edit the wording)", key=f"msg_{cid}", height=110)
                    if lang_key == "urdu":
                        rtl(text)
                    ok, problem = reminders.check_draft(text, draft["amount"])
                    phone_raw = st.text_input("WhatsApp number (optional)", placeholder="0300 1234567", key=f"ph_{cid}")
                    number, phone_err = reminders.normalize_phone(phone_raw)
                    if not ok:
                        st.error(problem)
                    elif phone_err:
                        st.error(phone_err)
                    else:
                        label = "📲 Open chat in WhatsApp" if number else "📲 Choose contact in WhatsApp"
                        st.link_button(label, reminders.whatsapp_url(number, text), width="stretch")
                        st.caption("This only opens WhatsApp with the draft. You send it yourself; "
                                   "it doesn't mean the message was delivered or paid.")

# ================= 4. HISTORY =================
with tab_history:
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
        tx = pd.DataFrame([{"date": csv_safe(e["date"]), "name": csv_safe(e["name"]),
                            "name_latin": csv_safe(e["name_latin"]), "details": csv_safe(e["details"]),
                            "type": e["kind"], "amount": str(e["amount"]), "page": csv_safe(e["page_id"]),
                            "row": csv_safe(e["row_ref"]), "source": e["source"]} for e in entries])
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

if show_debug:
    with st.sidebar:
        st.json({"page_id": (ss.page or {}).get("page_id"), "drafts": list(ss.drafts),
                 "model": getattr(get_provider(), "last_model", None)})
