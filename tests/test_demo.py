"""Live demo: sandbox accounts run the real pipeline against a simulated inbox, and nothing leaves the server."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import demo
from app.agent import actions
from app.db import session_scope, utcnow
from app.main import app
from app.models import Action, Commitment, Event, Message, User
from tests.fakes import FakeLLM
from tests.helpers import make_active_user

H = {"X-Requested-With": "aide"}


@pytest.fixture(autouse=True)
def clean_demo_state(monkeypatch):
    demo.purge_all_for_tests()
    # Run demo steps inline so tests are deterministic (production runs them on a background thread).
    monkeypatch.setattr(demo, "start_run", lambda uid, what: demo.RUNS[what](uid) or True)
    yield
    demo.purge_all_for_tests()


def _start(c: TestClient) -> int:
    r = c.post("/api/demo/start", json={"tz": "Asia/Kolkata"}, headers=H)
    assert r.status_code == 200, r.text
    with session_scope() as s:
        return s.scalar(select(func.max(User.id)).where(User.demo.is_(True)))


def test_demo_runs_the_real_pipeline_without_touching_the_outside_world(channel, fake_llm):
    c = TestClient(app, base_url="https://testserver")
    uid = _start(c)
    me = c.get("/api/me").json()
    assert me["demo"] is True and me["phone"] == "demo"

    with session_scope() as s:
        # Inbox sync went through the simulated Gmail: 9 emails, the newsletter filtered out.
        assert s.scalar(select(func.count()).select_from(Event).where(Event.user_id == uid, Event.source == "gmail")) == 9
        assert s.scalar(select(func.count()).select_from(Event).where(Event.user_id == uid, Event.source == "calendar")) >= 3
        assert s.scalar(select(func.count()).select_from(Commitment).where(Commitment.user_id == uid)) >= 3

    texts = [m["text"] for m in c.get("/api/messages").json()]
    assert "live demo" in texts[0]
    assert any("Call with Anika" in t for t in texts), texts
    assert channel.sent == []  # nothing went to WhatsApp

    # Approving an email "sends" it into the simulated mailbox only.
    with session_scope() as s:
        user = s.get(User, uid)
        actions.propose(s, user, "send_email", {"to": [demo.RAVI], "subject": "GST invoice", "body": "Attached."}, "Email Ravi")
    pending = c.get("/api/approvals").json()
    email = next(p for p in pending if p["kind"] == "send_email")
    assert "Sent to" in c.post(f"/api/approvals/{email['id']}/approve", headers=H).json()["result"]
    world = c.get("/api/demo/world").json()
    assert world["sent"][0]["to"] == [demo.RAVI]
    assert any(m["sent"] and m["subject"] == "GST invoice" for m in world["inbox"])
    assert channel.sent == []


def test_web_tasks_are_simulated_for_demo_accounts(channel, fake_llm):
    c = TestClient(app, base_url="https://testserver")
    uid = _start(c)
    with session_scope() as s:
        user = s.get(User, uid)
        a = actions.propose(s, user, "browser_task", {"goal": "Book a plumber for Saturday", "start_url": "https://example.com"},
                            "Book a plumber")
        result = actions.execute(s, user, a, llm=fake_llm)
        assert result.startswith("Demo:") and "Nothing was booked" in result
        assert s.get(Action, a.id).status == "executed"


def test_new_email_scenario_reaches_the_agent(channel, fake_llm):
    c = TestClient(app, base_url="https://testserver")
    uid = _start(c)
    fake_llm.turns = [FakeLLM.say("Meera wants 200 registers by Friday. I've drafted a quote reply for you.")]
    assert c.post("/api/demo/run", json={"what": "email"}, headers=H).status_code == 200
    last = c.get("/api/messages").json()[-1]["text"]
    assert last.startswith("*New email from Meera Iyer*") and "200 registers" in last
    with session_scope() as s:
        assert s.scalar(select(Event.subject).where(Event.user_id == uid, Event.subject.like("Order:%"))) is not None
    assert c.post("/api/demo/run", json={"what": "nonsense"}, headers=H).status_code == 422


def test_reset_gives_a_fresh_sandbox_and_removes_the_old_one(channel, fake_llm):
    c = TestClient(app, base_url="https://testserver")
    old = _start(c)
    with session_scope() as s:
        old_phone = s.get(User, old).phone
    assert c.post("/api/demo/reset", headers=H).status_code == 200
    with session_scope() as s:
        assert s.scalar(select(User).where(User.phone == old_phone)) is None
        assert s.scalar(select(func.count()).select_from(User).where(User.demo.is_(True))) == 1
    assert c.get("/api/me").json()["demo"] is True
    assert "live demo" in c.get("/api/messages").json()[0]["text"]


def test_demo_limits_and_expiry(channel, fake_llm):
    c = TestClient(app, base_url="https://testserver")
    for _ in range(demo.MAX_DEMOS_PER_IP_PER_HOUR):
        assert c.post("/api/demo/start", json={}, headers=H).status_code == 200
    assert c.post("/api/demo/start", json={}, headers=H).status_code == 429

    from app.config import get_settings

    get_settings().demo_messages = 1
    fake_llm.turns = [FakeLLM.say("Hello!")]
    assert c.post("/api/chat", json={"text": "hi"}, headers=H).json()["reply"] == "Hello!"
    assert "used all its messages" in c.post("/api/chat", json={"text": "again"}, headers=H).json()["reply"]

    with session_scope() as s:
        for u in s.scalars(select(User).where(User.demo.is_(True))).all():
            u.created_at = utcnow() - demo.DEMO_TTL - timedelta(minutes=1)
    with session_scope() as s:
        assert demo.delete_expired(s) == demo.MAX_DEMOS_PER_IP_PER_HOUR
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(User).where(User.demo.is_(True))) == 0
        assert s.scalar(select(func.count()).select_from(Message)) == 0


def test_real_accounts_cannot_use_demo_controls(channel, fake_llm):
    from tests.test_web import _signed_in

    make_active_user()
    c = _signed_in(channel)
    assert c.get("/api/demo/status").status_code == 404
    assert c.post("/api/demo/run", json={"what": "brief"}, headers=H).status_code == 404
    assert c.get("/api/me").json()["demo"] is False
