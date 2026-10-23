"""End-to-end app tests with Streamlit's AppTest. Sample replay only: no API key, no network."""
import sys
from pathlib import Path

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extract import rows_to_entries  # noqa: E402

APP = str(ROOT / "app.py")


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")


def new_app():
    return AppTest.from_file(APP, default_timeout=60).run()


def button(at, text):
    return next(b for b in at.button if text in b.label)


def metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


def goto(at, step_number):
    radio = next(r for r in at.radio if r.label == "Step")
    radio.set_value(radio.options[step_number - 1]).run()


def replay_and_confirm(at, sample="Urdu table"):
    button(at, f"Sample replay: {sample}").click().run()
    button(at, "Replay verified transcription").click().run()
    button(at, "Review").click().run()          # Next → button
    button(at, "Confirm page").click().run()    # confirming jumps straight to Collect
    return at


def test_next_and_back_buttons_always_move_between_steps():
    at = new_app()
    for expected in ("Review", "Collect", "History"):
        next(b for b in at.button if b.key and b.key.startswith("next_")).click().run()
        assert expected in next(r for r in at.radio if r.label == "Step").value
    next(b for b in at.button if b.key and b.key.startswith("back_")).click().run()
    assert "Collect" in next(r for r in at.radio if r.label == "Step").value
    assert not at.exception


def test_urdu_replay_confirm_and_payment():
    at = replay_and_confirm(new_app())
    assert not at.exception
    assert "Collect" in next(r for r in at.radio if r.label == "Step").value
    assert metric(at, "Total to collect") == "Rs. 14,700"
    form_inputs = [t for t in at.text_input if t.label == "Amount (Rs.)"]
    usman_idx = next(i for i, e in enumerate(at.expander) if "عثمان" in e.label)
    form_inputs[usman_idx].set_value("1,000")
    [b for b in at.button if "Record payment" in b.label][usman_idx].click().run()
    assert not at.exception
    assert metric(at, "Total to collect") == "Rs. 13,700"
    assert any("عثمان" in e.label and "3,000" in e.label for e in at.expander)


def test_roman_replay_total():
    at = replay_and_confirm(new_app(), "Roman Urdu page")
    assert metric(at, "Total to collect") == "Rs. 3,950"


def test_payment_invalidates_old_draft():
    at = replay_and_confirm(new_app(), "Roman Urdu page")
    ali = next(i for i, e in enumerate(at.expander) if "Ali bhai" in e.label)
    next(b for b in at.button if b.key == "prep_ali bhai").click().run()
    assert any("400" in t.value for t in at.text_area)
    [t for t in at.text_input if t.label == "Amount (Rs.)"][ali].set_value("100")
    [b for b in at.button if "Record payment" in b.label][ali].click().run()
    assert not any("400" in t.value for t in at.text_area), "stale 400 draft still visible"
    assert any("Ali bhai" in e.label and "300" in e.label for e in at.expander)


def test_business_change_invalidates_draft():
    at = replay_and_confirm(new_app(), "Roman Urdu page")
    [b for b in at.button if "Prepare draft" in b.label][0].click().run()
    assert at.text_area
    next(t for t in at.text_input if t.label == "Shop / academy name").set_value("New Shop").run()
    assert not at.text_area, "draft for the old shop name is still shown"


def test_confirm_with_unclear_rows_keeps_them_pending_and_fixable():
    at = new_app()
    result = {"rows": [{"row_ref": "1", "name": "Ali", "owed": "900"},
                       {"row_ref": "2", "name": "Hina", "owed": "Rs [unreadable]"}]}
    entries, evidence = rows_to_entries("p-test", result)
    at.session_state["page"] = {"page_id": "p-test", "image": Image.new("RGB", (40, 40), "white"),
                                "label": "test page", "is_demo": None, "rotation": 0, "result": result,
                                "entries": entries, "evidence": evidence, "error": None, "seconds": 1}
    goto(at, 2)
    confirm = button(at, "Confirm")
    assert "keep 1 for checking" in confirm.label
    confirm.click().run()
    assert metric(at, "Total to collect") == "Rs. 900"   # Hina's unknown amount is not counted
    assert metric(at, "Rows to check") == "1"
    assert not any(b.key == "prep_hina" for b in at.button)  # no reminder for an unchecked customer
    fix_amount = next(t for t in at.text_input if t.label == "Amount (Rs.)" and "unreadable" in t.value)
    fix_amount.set_value("750")
    button(at, "Save fix").click().run()
    assert not at.exception
    assert metric(at, "Total to collect") == "Rs. 1,650" and metric(at, "Rows to check") == "0"


def test_double_tap_payment_is_recorded_once_with_feedback():
    at = replay_and_confirm(new_app(), "Roman Urdu page")
    usman = next(i for i, e in enumerate(at.expander) if "Usman" in e.label)
    for _ in range(2):
        [t for t in at.text_input if t.label == "Amount (Rs.)"][usman].set_value("1000")
        [b for b in at.button if "Record payment" in b.label][usman].click().run()
    assert metric(at, "Total to collect") == "Rs. 2,950"  # was 1,950 before the fix
    assert any("already recorded" in s.value for s in at.success)


def test_payment_feedback_and_overpayment_shows_credit():
    at = replay_and_confirm(new_app(), "Roman Urdu page")
    ali = next(i for i, e in enumerate(at.expander) if "Ali bhai" in e.label)
    [t for t in at.text_input if t.label == "Amount (Rs.)"][ali].set_value("500")
    [b for b in at.button if "Record payment" in b.label][ali].click().run()
    assert any("Rs. 100 more than they owed" in s.value for s in at.success)
    assert any("Ali bhai" in e.label and "Credit" in e.label for e in at.expander)
    assert not any(b.key == "prep_ali bhai" for b in at.button)  # no reminder to a customer in credit


def test_confirmed_page_review_is_locked():
    at = replay_and_confirm(new_app(), "Roman Urdu page")
    goto(at, 2)
    assert any("already in your ledger" in i.value for i in at.info)
    assert not any("Confirm" in b.label for b in at.button)


def test_new_photo_clears_old_results():
    at = new_app()
    button(at, "Sample replay: Roman Urdu page").click().run()
    button(at, "Replay verified transcription").click().run()
    assert at.session_state.page["entries"]
    button(at, "Sample replay: Urdu table").click().run()
    assert at.session_state.page["entries"] is None  # old ledger not shown for the new image


def test_live_read_without_key_fails_cleanly():
    at = new_app()
    button(at, "Sample replay: Roman Urdu page").click().run()
    button(at, "Read with Gemma 4").click().run()
    assert not at.exception
    assert at.session_state.page["entries"] is None
    assert "API key" in at.session_state.page["error"]


def test_sessions_are_isolated():
    a = replay_and_confirm(new_app())
    b = new_app()
    goto(b, 3)
    assert metric(a, "Total to collect") == "Rs. 14,700"
    assert not b.metric  # second session's demo ledger is empty
