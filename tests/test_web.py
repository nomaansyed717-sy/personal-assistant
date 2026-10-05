"""Web app: homepage, sign-in by WhatsApp code, chat, approvals, memory, tasks, vault, settings, CSRF."""
import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent import actions
from app.db import session_scope
from app.main import app
from app.models import User
from tests.fakes import FakeLLM
from tests.helpers import PHONE, make_active_user

H = {"X-Requested-With": "aide"}


def _signed_in(channel) -> TestClient:
    c = TestClient(app, base_url="https://testserver")
    assert c.post("/api/login/start", json={"phone": PHONE}, headers=H).status_code == 200
    code = re.search(r"\*(\d{6})\*", channel.sent[-1][1]).group(1)
    r = c.post("/api/login/verify", json={"phone": PHONE, "code": code}, headers=H)
    assert r.status_code == 200 and "aide_session" in r.cookies
    return c


def test_homepage_and_app_shell_render():
    c = TestClient(app, base_url="https://testserver")
    home = c.get("/")
    assert home.status_code == 200 and "Your chief of staff lives in your WhatsApp." in home.text
    shell = c.get("/app")
    assert shell.status_code == 200 and "Content-Security-Policy" in shell.headers and "Sign in with the WhatsApp number" in shell.text


def test_login_requires_the_code_and_csrf(channel):
    make_active_user()
    c = TestClient(app, base_url="https://testserver")
    assert c.get("/api/me").status_code == 401
    assert c.post("/api/login/start", json={"phone": PHONE}).status_code == 403  # no CSRF header
    c.post("/api/login/start", json={"phone": PHONE}, headers=H)
    assert c.post("/api/login/verify", json={"phone": PHONE, "code": "000000"}, headers=H).status_code == 400
    # unknown numbers get the same answer and no message
    before = len(channel.sent)
    assert c.post("/api/login/start", json={"phone": "+15550001111"}, headers=H).json()["ok"]
    assert len(channel.sent) == before


def test_signed_in_user_can_do_everything(channel, fake_google, fake_llm):
    uid = make_active_user()
    c = _signed_in(channel)
    assert c.get("/api/me").json()["assistant_name"] == "Aide"

    # chat runs the same brain as WhatsApp
    fake_llm.turns = [FakeLLM.say("Here's your plan.")]
    assert c.post("/api/chat", json={"text": "plan my week"}, headers=H).json()["reply"] == "Here's your plan."
    assert [m["text"] for m in c.get("/api/messages").json()][-2:] == ["plan my week", "Here's your plan."]

    # approvals with buttons
    with session_scope() as s:
        actions.propose(s, s.get(User, uid), "send_email", {"to": ["ravi@distrib.com"], "subject": "Hi", "body": "Hello"},
                        "Email Ravi")
    pending = c.get("/api/approvals").json()
    assert len(pending) == 1
    assert c.post(f"/api/approvals/{pending[0]['id']}/approve").status_code == 403  # CSRF
    assert c.post(f"/api/approvals/{pending[0]['id']}/approve", headers=H).json()["result"] == "Sent to ravi@distrib.com"
    assert len(fake_google.sent) == 1
    act = c.get("/api/activity").json()
    assert any(d["action"] == "executed" for d in act["done"])

    # memory, goals, tasks, skills
    c.post("/api/memories", json={"text": "Never schedule calls before 10am"}, headers=H)
    mems = c.get("/api/memories").json()
    assert mems[0]["text"] == "Never schedule calls before 10am"
    c.delete(f"/api/memories/{mems[0]['id']}", headers=H)
    assert c.get("/api/memories").json() == []
    assert c.post("/api/goals", json={"title": "Launch Pune store"}, headers=H).status_code == 200
    assert c.post("/api/tasks", json={"title": "Watch kettle price", "instruction": "Check the page",
                                      "schedule": "every 12h"}, headers=H).status_code == 200
    task = c.get("/api/tasks").json()[0]
    assert task["schedule"] == "every 12h" and "NOTHING_NEW" in task["instruction"]
    assert c.post("/api/tasks", json={"title": "Too often", "instruction": "too often", "schedule": "every 1m"},
                  headers=H).status_code == 400
    assert any(s["name"] == "lead-reply" for s in c.get("/api/skills").json())
    planned = c.get("/api/activity").json()["planned"]
    assert any(p["what"] == "Watch kettle price" for p in planned)

    # vault: write-only from the browser's point of view
    c.post("/api/vault", json={"label": "Amazon", "site": "amazon.in", "username": "sam@x.com", "secret": "hunter2"}, headers=H)
    listing = c.get("/api/vault").text
    assert "Amazon" in listing and "hunter2" not in listing and "sam@x.com" not in listing

    # settings
    assert c.patch("/api/settings", json={"assistant_name": "Pumpkin", "persona": "Witty", "timezone": "Asia/Kolkata",
                                          "ideas_enabled": False}, headers=H).status_code == 200
    me = c.get("/api/me").json()
    assert me["assistant_name"] == "Pumpkin" and me["ideas_enabled"] is False and me["timezone"] == "Asia/Kolkata"
    assert c.patch("/api/settings", json={"timezone": "Mars/Base"}, headers=H).status_code == 400

    # sign out
    c.post("/api/logout", headers=H)
    assert c.get("/api/me").status_code == 401


def test_users_cannot_touch_each_others_data(channel, fake_llm):
    other = make_active_user(phone="+447700900123")
    with session_scope() as s:
        a = actions.propose(s, s.get(User, other), "send_email",
                            {"to": ["x@y.com"], "subject": "s", "body": "b"}, "Other's email")
        aid = a.id
    make_active_user()
    c = _signed_in(channel)
    assert c.get("/api/approvals").json() == []
    assert c.post(f"/api/approvals/{aid}/approve", headers=H).status_code == 404
    with session_scope() as s:
        assert s.scalar(select(User).where(User.phone == "+447700900123")) is not None
