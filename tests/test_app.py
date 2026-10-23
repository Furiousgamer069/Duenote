"""End-to-end app tests with Streamlit's AppTest. Sample replay only: no API key, no network."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")


def button(at, text):
    return next(b for b in at.button if text in b.label)


def metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


def replay_and_confirm(at, sample="Urdu table"):
    button(at, f"Sample replay: {sample}").click().run()
    button(at, "Replay verified transcription").click().run()
    button(at, "Confirm page").click().run()
    return at


def test_urdu_replay_confirm_and_payment():
    at = replay_and_confirm(AppTest.from_file(APP, default_timeout=60).run())
    assert not at.exception
    assert metric(at, "Total to collect") == "Rs. 14,700"
    # record Usman's (عثمان) Rs. 1,000 payment
    form_inputs = [t for t in at.text_input if t.label == "Amount (Rs.)"]
    usman_idx = next(i for i, e in enumerate(at.expander) if "عثمان" in e.label)
    form_inputs[usman_idx].set_value("1,000")
    [b for b in at.button if "Record payment" in b.label][usman_idx].click().run()
    assert not at.exception
    assert metric(at, "Total to collect") == "Rs. 13,700"
    assert any("عثمان" in e.label and "3,000" in e.label for e in at.expander)


def test_roman_replay_total():
    at = replay_and_confirm(AppTest.from_file(APP, default_timeout=60).run(), "Roman Urdu page")
    assert metric(at, "Total to collect") == "Rs. 3,950"


def test_edit_invalidates_old_draft():
    at = AppTest.from_file(APP, default_timeout=60).run()
    button(at, "Sample replay: Roman Urdu page").click().run()
    button(at, "Replay verified transcription").click().run()
    button(at, "Confirm page").click().run()
    ali = next(i for i, e in enumerate(at.expander) if "Ali bhai" in e.label)
    next(b for b in at.button if b.key == "prep_ali bhai").click().run()
    msgs = [t.value for t in at.text_area]
    assert any("400" in m for m in msgs)
    # record a payment for Ali -> ledger revision changes -> draft must disappear immediately
    amount_inputs = [t for t in at.text_input if t.label == "Amount (Rs.)"]
    amount_inputs[ali].set_value("100")
    [b for b in at.button if "Record payment" in b.label][ali].click().run()
    assert not any("400" in t.value for t in at.text_area), "stale 400 draft still visible"
    assert any("Ali bhai" in e.label and "300" in e.label for e in at.expander)


def test_business_change_invalidates_draft():
    at = AppTest.from_file(APP, default_timeout=60).run()
    replay_and_confirm(at, "Roman Urdu page")
    [b for b in at.button if "Prepare draft" in b.label][0].click().run()
    assert at.text_area
    next(t for t in at.text_input if t.label == "Shop / academy name").set_value("New Shop").run()
    assert not at.text_area, "draft for the old shop name is still shown"


def test_review_edit_blocks_and_unblocks_confirm():
    at = AppTest.from_file(APP, default_timeout=60).run()
    button(at, "Sample replay: Roman Urdu page").click().run()
    button(at, "Replay verified transcription").click().run()
    assert any("Confirm page" in b.label for b in at.button)


def test_new_photo_clears_old_results():
    at = AppTest.from_file(APP, default_timeout=60).run()
    button(at, "Sample replay: Roman Urdu page").click().run()
    button(at, "Replay verified transcription").click().run()
    assert at.session_state.page["entries"]
    button(at, "Sample replay: Urdu table").click().run()
    assert at.session_state.page["entries"] is None  # old ledger not shown for the new image


def test_live_read_without_key_fails_cleanly():
    at = AppTest.from_file(APP, default_timeout=60).run()
    button(at, "Sample replay: Roman Urdu page").click().run()
    button(at, "Read with Gemma 4").click().run()
    assert not at.exception
    assert at.session_state.page["entries"] is None
    assert "API key" in at.session_state.page["error"]


def test_sessions_are_isolated():
    a = replay_and_confirm(AppTest.from_file(APP, default_timeout=60).run())
    b = AppTest.from_file(APP, default_timeout=60).run()
    assert metric(a, "Total to collect") == "Rs. 14,700"
    assert not b.metric  # second session's demo ledger is empty
