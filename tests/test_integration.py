"""Reminders, phones, provider failures, extraction parsing and image safety. No network."""
import io
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import images  # noqa: E402
import provider as provider_mod  # noqa: E402
import reminders  # noqa: E402
from extract import extract_page, rows_to_entries, validate_output  # noqa: E402
from provider import GemmaProvider, ProviderError  # noqa: E402


# ---------- reminders ----------
def test_template_inserts_exact_amount_and_validates():
    text = reminders.draft("Usman", Decimal("3550"), "Bismillah Store", "shop", "roman")
    assert "Rs. 3,550" in text and "Bismillah Store" in text
    assert reminders.check_draft(text, Decimal("3550"))[0]
    urdu = reminders.draft("عثمان", Decimal("3550.50"), "Shop", "shop", "urdu")
    assert "3,550.50" in urdu and reminders.check_draft(urdu, Decimal("3550.50"))[0]


def test_edited_draft_with_wrong_amount_is_blocked():
    ok, msg = reminders.check_draft("Assalam-o-Alaikum, aapka baqaya Rs. 900 hai", Decimal("500"))
    assert not ok and "900" in msg
    assert not reminders.check_draft("Assalam-o-Alaikum, please pay soon", Decimal("500"))[0]
    assert reminders.check_draft("baqaya Rs. ۵۰۰ hai", Decimal("500"))[0]  # Urdu digits fine


@pytest.mark.parametrize("raw, expected", [
    ("0300 1234567", "923001234567"), ("+92 300 1234567", "923001234567"), ("0092-300-1234567", "923001234567"),
    ("923001234567", "923001234567"), ("۰۳۰۰۱۲۳۴۵۶۷", "923001234567"), ("", "")])
def test_phone_normalization(raw, expected):
    assert reminders.normalize_phone(raw) == (expected, None)


@pytest.mark.parametrize("raw", ["12345", "0300123456", "+1 555 123 4567", "04212345678", "abc"])
def test_bad_phones_rejected(raw):
    number, err = reminders.normalize_phone(raw)
    assert number == "" and err


def test_display_phone():
    assert reminders.display_phone("923001234567") == "+92 300 1234567" and reminders.display_phone("") == ""


def test_saved_contact_persists(tmp_path):
    from store import Store
    path = str(tmp_path / "c.db")
    Store(path).save_contact("usman", "923001234567", "2026-10-30")
    assert Store(path).contact("usman") == {"phone": "923001234567", "due_date": "2026-10-30"}
    assert Store(path).contact("nobody") == {"phone": "", "due_date": ""}


def test_blank_phone_link_lets_user_choose_contact():
    assert reminders.whatsapp_url("", "hi there") == "https://wa.me/?text=hi%20there"


# ---------- extraction parsing ----------
class FakeProvider:
    def __init__(self, *answers):
        self.answers, self.calls, self.last_model = list(answers), 0, "fake"

    def generate(self, contents):
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


GOOD = '{"page_kind":"transactions","written_total":null,"rows":[{"row_ref":"1","name":"Ali","owed":"1,150"}]}'


def test_extract_valid_json_with_chatter():
    result = extract_page(FakeProvider("Sure! ```json\n" + GOOD + "\n```"), None)
    entries, _ = rows_to_entries("p", result)
    assert entries[0]["amount"] == Decimal("1150") and not result["repaired"]


def test_malformed_json_gets_one_repair_then_fails():
    p = FakeProvider("not json at all", GOOD)
    assert extract_page(p, None)["repaired"] and p.calls == 2
    with pytest.raises(ValueError):
        extract_page(FakeProvider("garbage", "still garbage"), None)


def test_schema_validation():
    assert validate_output({"rows": "nope"})[0] is None
    result, problems = validate_output({"rows": [{"name": "A"}, "bad"]})
    assert len(result["rows"]) == 1 and problems


def test_unclear_and_missing_amounts_stay_unresolved():
    entries, _ = rows_to_entries("p", {"rows": [
        {"row_ref": "1", "name": "A", "unclear_amount": "500"},
        {"row_ref": "2", "name": "B"},
        {"row_ref": "3", "name": "C", "owed": "smudged"}]})
    assert all(not e["resolved"] for e in entries) and len(entries) == 3


# ---------- provider failures (simulated, no network) ----------
class FakeErr(Exception):
    pass


def test_missing_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    with pytest.raises(ProviderError) as e:
        GemmaProvider(api_key=None).generate(["x"])
    assert e.value.kind == "missing_key"


@pytest.mark.parametrize("code, kind", [(401, "auth"), (403, "auth"), (404, "bad_model"), (429, "rate_limit")])
def test_client_errors_classified(code, kind):
    from google.genai import errors
    err = errors.ClientError(code, {"error": {"code": code, "message": "x", "status": "X"}})
    assert GemmaProvider._classify(err).kind == kind


def test_retries_server_errors_then_succeeds_without_final_sleep(monkeypatch):
    from google.genai import errors
    sleeps = []
    monkeypatch.setattr(provider_mod.time, "sleep", lambda s: sleeps.append(s))

    class Client:
        class models:
            n = 0

            @classmethod
            def generate_content(cls, model, contents):
                cls.n += 1
                if cls.n < 3:
                    raise errors.ServerError(503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}})
                return type("R", (), {"text": "ok"})()

    p = GemmaProvider(api_key="k", models=["a", "b"])
    p._client = Client()
    assert p.generate(["x"]) == "ok" and sleeps == [1, 2]

    Client.models.n = -100  # always fail
    sleeps.clear()
    with pytest.raises(ProviderError) as e:
        p.generate(["x"])
    assert e.value.kind == "server" and len(sleeps) == p.max_attempts - 1  # no sleep after last try


def test_race_returns_the_model_that_answers_while_the_other_is_busy(monkeypatch):
    from google.genai import errors
    monkeypatch.setattr(provider_mod.time, "sleep", lambda s: None)

    class Client:
        class models:
            @staticmethod
            def generate_content(model, contents):
                if model == "busy":
                    raise errors.ServerError(503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}})
                return type("R", (), {"text": f"answer from {model}"})()

    p = GemmaProvider(api_key="k", models=["busy", "ok"], race=True)
    p._client = Client()
    assert p.generate(["x"]) == "answer from ok" and p.last_model == "ok"


def test_race_reports_rate_limit_when_all_fail(monkeypatch):
    from google.genai import errors
    monkeypatch.setattr(provider_mod.time, "sleep", lambda s: None)

    def fail(model, contents):
        if model == "a":
            raise errors.ClientError(429, {"error": {"code": 429, "message": "slow down", "status": "RESOURCE_EXHAUSTED"}})
        raise errors.ServerError(500, {"error": {"code": 500, "message": "x", "status": "INTERNAL"}})

    p = GemmaProvider(api_key="k", models=["a", "b"], race=True, max_attempts=2)
    p._client = type("C", (), {"models": type("M", (), {"generate_content": staticmethod(fail)})})()
    with pytest.raises(ProviderError) as e:
        p.generate(["x"])
    assert e.value.kind == "rate_limit"


def test_empty_output_is_an_error():
    p = GemmaProvider(api_key="k", models=["a"], max_attempts=1)
    p._client = type("C", (), {"models": type("M", (), {"generate_content": staticmethod(
        lambda model, contents: type("R", (), {"text": ""})())})})()
    with pytest.raises(ProviderError) as e:
        p.generate(["x"])
    assert e.value.kind == "empty"


# ---------- images ----------
def _png(size=(50, 40)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return buf.getvalue()


def test_corrupt_and_empty_uploads_rejected():
    for bad in (b"", b"not an image", _png()[:30]):
        with pytest.raises(images.ImageProblem):
            images.load_photo(bad)


def test_size_limit(monkeypatch):
    monkeypatch.setattr(images, "MAX_BYTES", 10)
    with pytest.raises(images.ImageProblem):
        images.load_photo(_png())


def test_exif_rotation_and_resize():
    img = Image.new("RGB", (200, 100), "white")
    exif = img.getexif()
    exif[0x0112] = 6  # "rotate 90" orientation tag, as phones write it
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    loaded, pid = images.load_photo(buf.getvalue())
    assert loaded.size == (100, 200) and pid.startswith("p-")
    assert max(images.for_model(Image.new("RGB", (4000, 3000))).size) == images.MODEL_LONG_SIDE
