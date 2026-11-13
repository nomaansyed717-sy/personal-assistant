import hashlib
import hmac
from datetime import timedelta

import pytest

from app.channels.whatsapp import parse_webhook, verify_signature
from app.context.rank import score
from app.crypto import CryptoError, decrypt, encrypt
from app.integrations.google import parse_gmail_message, strip_quoted
from app.messenger import split_message
from app.models import Commitment, Person
from app.util import guess_timezone, normalize_phone
from tests.fakes import FakeGoogle, now


def test_signature_check():
    body = b'{"a":1}'
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert verify_signature(body, sig, "s3cret")
    assert not verify_signature(body, "sha256=bad", "s3cret")
    assert not verify_signature(body, None, "s3cret")


def test_parse_webhook_text_and_button_and_status():
    payload = {
        "entry": [{"changes": [{"value": {
            "contacts": [{"wa_id": "447700900123", "profile": {"name": "Ana"}}],
            "messages": [
                {"from": "447700900123", "id": "w1", "type": "text", "text": {"body": " 1, 3 "}},
                {"from": "447700900123", "id": "w2", "type": "interactive", "interactive": {"button_reply": {"title": "Yes"}}},
                {"from": "447700900123", "id": "w3", "type": "audio", "audio": {"id": "m1", "mime_type": "audio/ogg"}},
                {"from": "447700900123", "id": "w4", "type": "video", "video": {"id": "m2"}},
                {"from": "447700900123", "id": "w5", "type": "image", "image": {"id": "m3", "mime_type": "image/jpeg", "caption": "receipt"}},
            ],
            "statuses": [{"id": "x", "status": "read"}],
        }}]}]
    }
    msgs = parse_webhook(payload)
    assert [m.text for m in msgs] == ["1, 3", "Yes", "", "", "receipt"]
    assert msgs[0].phone == "+447700900123" and msgs[0].profile_name == "Ana"
    assert [m.kind for m in msgs] == ["text", "button", "audio", "unsupported", "image"]
    assert msgs[2].media_id == "m1" and msgs[4].mime == "image/jpeg"


def test_phone_and_timezone_guess_global():
    assert normalize_phone("919876543210") == "+919876543210"
    assert guess_timezone("+919876543210") == "Asia/Kolkata"
    assert guess_timezone("+447700900123") == "Europe/London"
    assert guess_timezone("+447911123456") == "Europe/London"
    assert guess_timezone("+12125550123").startswith("America/")


def test_split_long_messages():
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(200))
    parts = split_message(text, 4000)
    assert all(len(p) <= 4000 for p in parts) and "".join(parts).count("line") == 200


def test_per_user_keys_are_isolated():
    token = encrypt(1, "hello")
    assert decrypt(1, token) == "hello"
    with pytest.raises(CryptoError):
        decrypt(2, token)


def test_gmail_parsing_and_quote_stripping():
    g = FakeGoogle()
    g.add_email("m1", "t1", "ravi@distrib.com", ["me@example.com"], "Hi", "New text\n\nOn Mon, 1 Jan 2026 Ravi wrote:\n> old", now(),
                from_name="Ravi")
    m = parse_gmail_message(g.messages["m1"])
    assert m["from_addr"] == "ravi@distrib.com" and m["from_name"] == "Ravi"
    assert m["body"] == "New text" and m["message_id_header"] == "<m1@mail.example.com>"
    assert strip_quoted("ok\n> quoted\nmore") == "ok\nmore"


def _c(**kw):
    defaults = dict(direction="user_owes", description="x", confidence=0.9, made_at=now() - timedelta(days=4), times_surfaced=0)
    defaults.update(kw)
    c = Commitment(**defaults)
    c.person = kw.get("person")
    c.project = None
    return c


def test_ranking_prefers_important_people_overdue_items_and_avoids_nagging():
    vip = Person(email="a@x.com", importance=0.9)
    minor = Person(email="b@x.com", importance=0.1)
    assert score(_c(person=vip)) > score(_c(person=minor))
    assert score(_c(person=minor, due_at=now() - timedelta(days=2))) > score(_c(person=minor))
    assert score(_c(person=vip)) > score(_c(person=vip, times_surfaced=3))
    assert score(_c(person=vip)) > score(_c(person=vip, direction="owed_to_user"))
    assert score(_c(person=vip, made_at=now() - timedelta(days=60))) < score(_c(person=vip))


def test_base_url_from_hosting_env(monkeypatch):
    from app.config import get_settings

    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "aide-production.up.railway.app")
    get_settings.cache_clear()
    assert get_settings().base_url == "https://aide-production.up.railway.app"
    get_settings.cache_clear()


def test_calendar_times_are_stored_in_utc():
    from datetime import UTC, datetime

    from app.integrations.google import _parse_dt

    dt = _parse_dt("2026-11-12T10:30:00+05:30")
    assert dt.tzinfo == UTC and dt.hour == 5 and dt.minute == 0
    assert _parse_dt("2026-11-12T10:30:00Z") == datetime(2026, 11, 12, 10, 30, tzinfo=UTC)
    assert _parse_dt("2026-11-12") == datetime(2026, 11, 12, tzinfo=UTC)


def test_approval_cards_drop_chat_only_instructions():
    from app.agent.actions import card_preview

    text = "You owe Ravi: send the invoice, due Friday\nReply with the number once it's handled, or 'snooze N'."
    assert card_preview(text) == "You owe Ravi: send the invoice, due Friday"
    assert card_preview("Send this?\n_Hi Ravi_") == "Send this?\n_Hi Ravi_"


def test_terms_redirects_to_privacy():
    from fastapi.testclient import TestClient

    from app.main import app

    r = TestClient(app).get("/terms", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == "/privacy"


def test_todays_events_follow_the_users_day_not_utcs():
    from datetime import UTC, datetime, time, timedelta

    from app.brief import todays_events
    from app.db import session_scope
    from app.models import Event, User
    from app.util import local_now, zone
    from tests.helpers import make_active_user

    uid = make_active_user(phone="+15550001111")
    with session_scope() as s:
        user = s.get(User, uid)
        user.timezone = "America/Los_Angeles"
        tz = zone(user.timezone)
        today = local_now(user.timezone).date()
        # 23:30 local is the next day in UTC; 00:30 tomorrow local is not today.
        late = datetime.combine(today, time(23, 30), tzinfo=tz).astimezone(UTC)
        tomorrow = datetime.combine(today + timedelta(days=1), time(0, 30), tzinfo=tz).astimezone(UTC)
        s.add(Event(user_id=uid, source="calendar", external_id="late", kind="calendar", subject="Late call", occurred_at=late))
        s.add(Event(user_id=uid, source="calendar", external_id="tmr", kind="calendar", subject="Tomorrow", occurred_at=tomorrow))
        s.flush()
        assert [e.subject for e in todays_events(s, user)] == ["Late call"]
