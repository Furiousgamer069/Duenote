"""DueNote: photo of a handwritten notebook -> ledger -> WhatsApp reminders.

Run:  .venv/Scripts/streamlit.exe run app.py
"""
import io
import os
import re
import urllib.parse

import streamlit as st
from PIL import Image

import khata

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")

st.set_page_config(page_title="DueNote", page_icon="📒", layout="centered")

# Sidebar: who is using the app
with st.sidebar:
    st.header("⚙️ Settings")
    mode_label = st.radio("Notebook type", ["🛒 Shop udhaar", "🎓 Tuition fees"])
    mode = "shop" if "Shop" in mode_label else "fees"
    business = st.text_input(
        "Your shop / academy name",
        "Bismillah General Store" if mode == "shop" else "Al-Noor Academy",
    )
    st.divider()
    st.caption("Built with **Gemma 4** (open-weight) · MIT licensed")
    st.caption("AI reads the handwriting. Python does all the maths.")

st.title("📒 DueNote")
st.write("Photo of your handwritten notebook → who owes what → polite **WhatsApp reminders** in Urdu.")


def whatsapp_link(phone, text):
    """Build a wa.me link. Pakistani numbers like 0300... become 92300..."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0"):
        digits = "92" + digits[1:]
    return f"https://wa.me/{digits}?text={urllib.parse.quote(text)}"


# Cache results: reading the same photo again is instant while the app is running
@st.cache_data(show_spinner=False)
def read_cached(image_bytes, mode):
    return khata.read_notebook(Image.open(io.BytesIO(image_bytes)).convert("RGB"), mode)


@st.cache_data(show_spinner=False)
def reminders_cached(balances, business, mode):
    return khata.write_reminders(balances, business, mode)


def to_bytes(image):
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


# ---------- Step 1: get the photo ----------
st.subheader("1. Snap your notebook")
tab_upload, tab_camera = st.tabs(["📁 Upload photo", "📷 Use camera"])
with tab_upload:
    uploaded = st.file_uploader("Notebook page", type=["png", "jpg", "jpeg"], label_visibility="collapsed")
with tab_camera:
    snapped = st.camera_input("Take a photo", label_visibility="collapsed")

col_a, col_b = st.columns(2)
if col_a.button("✨ Sample: Roman Urdu page", width="stretch"):
    st.session_state.photo = Image.open(os.path.join(SAMPLES, "khata_sample.png"))
if col_b.button("✨ Sample: Urdu table", width="stretch"):
    st.session_state.photo = Image.open(os.path.join(SAMPLES, "real_page.png"))
if uploaded or snapped:
    st.session_state.photo = Image.open(uploaded or snapped)

photo = st.session_state.get("photo")
if photo is not None:
    st.image(photo, caption="Your notebook page", width="stretch")
    if st.button("🔍 Read my notebook", type="primary", width="stretch"):
        with st.spinner("Gemma 4 is reading the handwriting... (can take 1–2 minutes)"):
            try:
                st.session_state.entries = read_cached(to_bytes(photo), mode)
                st.session_state.pop("reminders", None)
            except Exception as e:
                st.error(f"Couldn't read the page: {e}")

# ---------- Step 2: check entries and see balances ----------
if "entries" in st.session_state:
    st.subheader("2. Check the entries")
    st.caption("Handwriting can be messy. Fix any mistakes here before we calculate.")
    entries = st.data_editor(
        st.session_state.entries,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "amount": st.column_config.NumberColumn("amount (Rs.)", min_value=0, step=1),
            "type": st.column_config.SelectboxColumn("type", options=["owed", "paid"], required=True),
        },
        key="entries_editor",
    )

    balances = khata.compute_balances(entries)
    due = balances[balances["balance"] > 0]

    c1, c2, c3 = st.columns(3)
    c1.metric("Total to collect", f"Rs. {due['balance'].sum():,.0f}")
    c2.metric("People who owe", len(due))
    c3.metric("Fully paid", int((balances["balance"] <= 0).sum()))

    st.dataframe(
        balances.rename(columns={"name": "Name", "owed": "Owed", "paid": "Paid", "balance": "Balance"}),
        width="stretch",
        hide_index=True,
    )
    st.download_button(
        "⬇️ Download ledger (CSV for Excel)",
        balances.to_csv(index=False).encode("utf-8-sig"),
        file_name="khata_ledger.csv",
        mime="text/csv",
    )

    # ---------- Step 3: WhatsApp reminders ----------
    st.subheader("3. Send WhatsApp reminders")
    if due.empty:
        st.success("🎉 Everyone has paid. No reminders needed!")
    elif st.button("💬 Write reminders", type="primary", width="stretch"):
        with st.spinner("Gemma 4 is writing polite reminders..."):
            try:
                st.session_state.reminders = reminders_cached(balances, business, mode)
                for k in [k for k in st.session_state if k.startswith("lang_")]:
                    del st.session_state[k]  # fresh messages replace any old edits
            except Exception as e:
                st.error(f"Couldn't write reminders: {e}")

    reminders = st.session_state.get("reminders")
    if reminders and not due.empty:
        language = st.radio("Message language", ["Roman Urdu", "اردو"], horizontal=True)
        key = "roman" if language == "Roman Urdu" else "urdu"
        for row in due.itertuples():
            item = reminders.get(row.name)
            if not item:
                continue
            # When the language changes, load that version into the message box
            if st.session_state.get(f"lang_{row.name}") != key:
                st.session_state[f"msg_{row.name}"] = item.get(key, "")
                st.session_state[f"lang_{row.name}"] = key
            with st.expander(f"**{row.name}** owes Rs. {row.balance:,.0f}", expanded=True):
                text = st.text_area("Message", key=f"msg_{row.name}", height=120)
                phone = st.text_input("WhatsApp number (optional)", placeholder="0300 1234567", key=f"ph_{row.name}")
                st.link_button("📲 Open in WhatsApp", whatsapp_link(phone, text), width="stretch")
