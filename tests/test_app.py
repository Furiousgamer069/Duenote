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


def message(at, cid):
    return next(t.value for t in at.text_area if t.key == f"msg_{cid}")


def remind_links(at):
    return [b for b in at.get("link_button") if "Remind on WhatsApp" in b.proto.label]


def test_reminder_ready_without_extra_click_and_updates_after_payment():
    at = replay_and_confirm(new_app(), "Roman Urdu page")
    assert "Rs. 400" in message(at, "ali bhai") and "Bismillah General Store" in message(at, "ali bhai")
    # owner edits the wording, then a payment arrives
    next(t for t in at.text_area if t.key == "msg_ali bhai").set_value("Ali bhai, Rs. 400 baqaya hai. Shukriya").run()
    ali = next(i for i, e in enumerate(at.expander) if "Ali bhai" in e.label)
    [t for t in at.text_input if t.label == "Amount (Rs.)"][ali].set_value("100")
    [b for b in at.button if "Record payment" in b.label][ali].click().run()
    assert "Rs. 300" in message(at, "ali bhai") and "400" not in message(at, "ali bhai"), "stale 400 message"
    assert any("message was rewritten" in c.value for c in at.caption)


def test_edited_message_with_wrong_amount_disables_button():
    at = replay_and_confirm(new_app(), "Roman Urdu page")
    before = len(remind_links(at))
    next(t for t in at.text_area if t.key == "msg_ali bhai").set_value("Ali bhai, Rs. 900 baqaya hai").run()
    assert any("approved balance is Rs. 400" in e.value for e in at.error)
    assert len(remind_links(at)) == before - 1


def test_business_change_rewrites_message():
    at = replay_and_confirm(new_app(), "Roman Urdu page")
    assert "Bismillah General Store" in message(at, "usman")
    next(t for t in at.text_input if t.label == "Shop / academy name").set_value("New Shop").run()
    assert "New Shop" in message(at, "usman") and "Bismillah" not in message(at, "usman")


def test_save_whatsapp_number_validation_and_link():
    at = replay_and_confirm(new_app(), "Roman Urdu page")
    usman = next(i for i, e in enumerate(at.expander) if "Usman" in e.label)
    phone_inputs = [t for t in at.text_input if t.label == "WhatsApp number"]
    save_buttons = [b for b in at.button if "Save number" in b.label]
    phone_inputs[0].set_value("12345")          # Usman is the first due customer
    save_buttons[0].click().run()
    assert any("Pakistani mobile number" in e.value for e in at.error)
    [t for t in at.text_input if t.label == "WhatsApp number"][0].set_value("0300-1234567")
    [b for b in at.button if "Save number" in b.label][0].click().run()
    assert any("+92 300 1234567" in s.value for s in at.success)
    link = next(b for b in remind_links(at) if "+92 300 1234567" in b.proto.label)
    assert link.proto.url.startswith("https://wa.me/923001234567?text=") and "3%2C550" in link.proto.url
    assert usman == 0


def test_overdue_only_after_confirmed_due_date():
    from datetime import date, timedelta
    at = replay_and_confirm(new_app(), "Roman Urdu page")
    assert not any("Overdue" in e.label for e in at.expander)  # no due date saved yet
    [d for d in at.date_input if d.label == "Due date (optional)"][0].set_value(date.today() - timedelta(days=3))
    [b for b in at.button if "Save number" in b.label][0].click().run()
    assert any("Overdue" in e.label and "Usman" in e.label for e in at.expander)
    assert not any("Overdue" in e.label and "Ali bhai" in e.label for e in at.expander)


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
    assert not any(t.key == "msg_hina" for t in at.text_area)  # no reminder for an uncertain amount
    assert any("unlocks once you fix" in i.value for i in at.info)
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
    assert not any(t.key == "msg_ali bhai" for t in at.text_area)  # no reminder to a customer in credit
    assert not any(t.key == "msg_bilal" for t in at.text_area)     # nor to a settled one


def test_confirmed_page_review_is_locked():
    at = replay_and_confirm(new_app(), "Roman Urdu page")
    goto(at, 2)
    assert any("already in your ledger" in i.value for i in at.info)
    assert not any("Confirm" in b.label for b in at.button)


def _page(pid, label, rows=None):
    page = {"page_id": pid, "image": Image.new("RGB", (40, 40), "white"), "label": label, "is_demo": None,
            "rotation": 0, "result": None, "entries": None, "evidence": {}, "error": None, "seconds": None}
    if rows is not None:
        result = {"rows": rows}
        page["result"] = result
        page["entries"], page["evidence"] = rows_to_entries(pid, result)
        page["seconds"] = 1
    return page


def test_multiple_pages_reviewed_one_after_another():
    at = new_app()
    p1 = _page("p-1", "page1.jpg", [{"row_ref": "1", "name": "Ali", "owed": "900"}])
    p2 = _page("p-2", "page2.jpg", [{"row_ref": "1", "name": "Sara", "owed": "1,200"},
                                     {"row_ref": "2", "name": "Ali", "paid": "400"}])
    at.session_state["batch"] = {"p-1": p1, "p-2": p2}
    at.session_state["page"] = p1
    goto(at, 2)
    button(at, "Confirm").click().run()
    assert "Review" in next(r for r in at.radio if r.label == "Step").value   # moved on to page 2
    assert at.session_state.page["page_id"] == "p-2"
    assert any("Next: page2.jpg" in s.value for s in at.success)
    button(at, "Confirm").click().run()
    assert "Collect" in next(r for r in at.radio if r.label == "Step").value   # all done -> Collect
    assert metric(at, "Total to collect") == "Rs. 1,700"   # Ali 900-400 + Sara 1,200, across both pages
    assert not at.exception


def test_read_all_without_key_fails_cleanly_per_page():
    at = new_app()
    at.session_state["batch"] = {"p-1": _page("p-1", "a.jpg"), "p-2": _page("p-2", "b.jpg")}
    at.session_state["page"] = at.session_state["batch"]["p-1"]
    at.run()
    button(at, "Read all 2 pages").click().run()
    assert not at.exception
    assert all("API key" in p["error"] for p in at.session_state.batch.values())


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
