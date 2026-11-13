"""App-first: sign-in by email or SMS code, bearer tokens, in-app onboarding, push, Today, uploads."""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import otp, push
from app.db import session_scope
from app.main import _done_page, app
from app.messenger import send
from app.models import Commitment, Device, Message, User
from tests.fakes import FakeLLM

H = {"X-Requested-With": "aide"}
TOKEN = "ExponentPushToken[abcdefghijklmnop]"


@pytest.fixture(autouse=True)
def clean_outbox():
    otp.OUTBOX.clear()
    yield
    otp.OUTBOX.clear()


@pytest.fixture
def pushes():
    sent: list[dict] = []

    def fake(messages):
        sent.extend(messages)
        return [{"status": "ok"} for _ in messages]

    push.set_sender(fake)
    yield sent
    push.set_sender(None)


def _code() -> str:
    return re.search(r"\b(\d{6})\b", otp.OUTBOX[-1][1]).group(1)


def _app_client(email="asha@example.in") -> tuple[TestClient, dict]:
    c = TestClient(app, base_url="https://testserver")
    assert c.post("/api/auth/start", json={"email": email, "tz": "Asia/Kolkata"}, headers=H).status_code == 200
    r = c.post("/api/auth/verify", json={"email": email, "code": _code(), "client": "app"})
    assert r.status_code == 200, r.text
    return c, {"Authorization": f"Bearer {r.json()['token']}"}


def test_email_signup_onboarding_and_bearer_auth(pushes):
    c, auth = _app_client()
    me = c.get("/api/me", headers=auth).json()
    assert me["onboarding_state"] == "awaiting_consent" and me["channel"] == "app"
    assert me["email"] == "as•••@example.in" and me["phone"] is None and me["timezone"] == "Asia/Kolkata"

    # Bearer requests need no CSRF header; consent moves the user on.
    assert c.post("/api/onboarding/google", json={"client": "app"}, headers=auth).status_code == 400  # terms first
    r = c.post("/api/onboarding/consent", json={"accept": True, "name": "Asha Patil"}, headers=auth)
    assert r.json()["onboarding_state"] == "awaiting_connect"
    url = c.post("/api/onboarding/google", json={"client": "app"}, headers=auth).json()["url"]
    assert "/connect/google?s=" in url

    assert c.post("/api/devices", json={"token": TOKEN, "platform": "android"}, headers=auth).status_code == 200
    r = c.post("/api/onboarding/skip", headers=auth)
    assert r.json()["onboarding_state"] == "active"
    msgs = c.get("/api/messages", headers=auth).json()
    assert msgs[-1]["from"] == "assistant" and msgs[-1]["channel"] == "app" and "Welcome Asha" in msgs[-1]["text"]
    assert pushes and pushes[-1]["to"] == TOKEN and pushes[-1]["body"].startswith("Welcome Asha")
    after = msgs[-1]["id"]
    assert c.get(f"/api/messages?after={after}", headers=auth).json() == []


def test_same_email_signs_back_into_the_same_account():
    _app_client("Ravi@Example.com")
    _app_client("ravi@example.com")
    with session_scope() as s:
        assert len(s.scalars(select(User).where(User.email == "ravi@example.com")).all()) == 1


def test_phone_signup_guesses_timezone_and_codes_are_checked():
    c = TestClient(app, base_url="https://testserver")
    assert c.post("/api/auth/start", json={"phone": "+91 98765 43210"}, headers=H).json()["sent_to"] == "sms"
    assert otp.OUTBOX[-1][0] == "+919876543210"
    assert c.post("/api/auth/verify", json={"phone": "+919876543210", "code": "000000", "client": "app"}).status_code == 400
    r = c.post("/api/auth/verify", json={"phone": "+919876543210", "code": _code(), "client": "web"}, headers=H)
    assert r.status_code == 200 and "aide_session" in r.cookies
    me = c.get("/api/me").json()
    assert me["timezone"] == "Asia/Kolkata" and me["phone"].endswith("••••")
    # A code works once.
    with session_scope() as s:
        assert s.scalar(select(User).where(User.phone == "+919876543210")).onboarding_state == "awaiting_consent"


def test_bad_input_rate_limit_and_csrf():
    c = TestClient(app, base_url="https://testserver")
    assert c.post("/api/auth/start", json={"email": "not-an-email"}, headers=H).status_code == 400
    assert c.post("/api/auth/start", json={"phone": "123"}, headers=H).status_code == 400
    assert c.post("/api/auth/start", json={"email": "a@b.co"}).status_code == 403  # browser without CSRF header
    for _ in range(3):
        assert c.post("/api/auth/start", json={"email": "a@b.co"}, headers=H).status_code == 200
    assert c.post("/api/auth/start", json={"email": "a@b.co"}, headers=H).status_code == 429
    assert c.get("/api/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_push_respects_previews_and_drops_dead_tokens():
    sent = []

    def fake(messages):
        sent.extend(messages)
        return [{"status": "error", "details": {"error": "DeviceNotRegistered"}} for _ in messages]

    push.set_sender(fake)
    try:
        c, auth = _app_client()
        c.post("/api/devices", json={"token": TOKEN}, headers=auth)
        c.patch("/api/settings", json={"push_previews": False}, headers=auth)
        with session_scope() as s:
            user = s.scalar(select(User).where(User.email == "asha@example.in"))
            send(s, user, "Ravi is still waiting for the GST invoice.")
        assert sent[-1]["body"] == "You have a new message."
        with session_scope() as s:
            assert s.scalar(select(Device)) is None  # Expo said the token is dead
    finally:
        push.set_sender(None)


def test_today_and_loop_actions():
    c, auth = _app_client()
    c.post("/api/onboarding/consent", json={"accept": True, "name": "Asha"}, headers=auth)
    c.post("/api/onboarding/skip", headers=auth)
    with session_scope() as s:
        uid = s.scalar(select(User).where(User.email == "asha@example.in")).id
        s.add(Commitment(user_id=uid, direction="user_owes", description="Send Ravi the GST invoice"))
    t = c.get("/api/today", headers=auth).json()
    assert t["greeting"].endswith("Asha") and t["loops"][0]["description"] == "Send Ravi the GST invoice"
    cid = t["loops"][0]["id"]
    assert c.post(f"/api/loops/{cid}", json={"action": "done"}, headers=auth).status_code == 200
    assert c.get("/api/today", headers=auth).json()["loops"] == []


def test_upload_text_file_reaches_the_agent():
    from app import llm

    fake = FakeLLM()
    fake.turns = [FakeLLM.say("That's your packing list. Want me to set a reminder?")]
    llm.set_llm(fake)
    try:
        c, auth = _app_client()
        c.post("/api/onboarding/consent", json={"accept": True}, headers=auth)
        c.post("/api/onboarding/skip", headers=auth)
        r = c.post("/api/chat/upload", headers=auth, data={"caption": "what is this?"},
                   files={"file": ("list.txt", b"passport, charger, gifts", "text/plain")})
        assert r.status_code == 200 and "packing list" in r.json()["reply"]
        assert "passport, charger, gifts" in str(fake.complete_calls[-1])
        r = c.post("/api/chat/upload", headers=auth, files={"file": ("x.bin", b"\x00\x01", "application/zip")})
        assert "not application/zip" in r.json()["reply"]
        with session_scope() as s:
            assert s.scalar(select(Message).where(Message.direction == "in")).channel == "app"
    finally:
        llm.set_llm(None)


def test_google_return_page_deep_links_into_the_app():
    page = _done_page("You're connected", "Reading now.", "app")
    assert "aide://connected?ok=1" in page and "location.replace" in page
    assert 'href="/app"' in _done_page("You're connected", "Reading now.", "web")
