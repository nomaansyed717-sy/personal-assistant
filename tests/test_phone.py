"""Phone agent: the phone sends screens, the server returns steps, and logins and payments stay with the user."""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import llm, otp, push
from app.agent import actions
from app.db import session_scope
from app.main import app
from app.models import Action, PhoneJob, User
from tests.fakes import FakeLLM

H = {"X-Requested-With": "aide"}
APPS = [{"label": "redBus", "package": "in.redbus.android"}, {"label": "PhonePe", "package": "com.phonepe.app"},
        {"label": "IRCTC Rail Connect", "package": "cris.org.in.prs.ima"}]


def node(i, text="", cls="TextView", **flags):
    return {"id": i, "cls": cls, "text": text, "desc": "", "rid": "", "click": flags.get("click", False),
            "edit": flags.get("edit", False), "scroll": False, "pwd": flags.get("pwd", False)}


HOME = {"package": "com.android.launcher3", "nodes": [node(0, "redBus", click=True), node(1, "PhonePe", click=True)]}
SEARCH = {"package": "in.redbus.android", "nodes": [
    node(0, "From", "EditText", edit=True), node(1, "To", "EditText", edit=True), node(2, "Search buses", "Button", click=True)]}
LOGIN = {"package": "in.redbus.android", "nodes": [
    node(0, "Email", "EditText", edit=True), node(1, "", "EditText", edit=True, pwd=True), node(2, "Sign in", "Button", click=True)]}
REVIEW = {"package": "in.redbus.android", "nodes": [
    node(0, "Zingbus AC Sleeper, Fri 22:30, Pune to Aurangabad, Seat L4"), node(1, "Total ₹1,240"),
    node(2, "Proceed to pay ₹1,240", "Button", click=True)]}
UPI = {"package": "com.phonepe.app", "nodes": [node(0, "Enter UPI PIN")]}


class ScriptedLLM(FakeLLM):
    def __init__(self, decisions):
        super().__init__()
        self.decisions = list(decisions)
        self.extractors["next_step"] = lambda content: self.decisions.pop(0) if self.decisions else {"action": "wait", "thought": "", "progress": ""}


@pytest.fixture
def client():
    otp.OUTBOX.clear()
    sent = []
    push.set_sender(lambda msgs: (sent.extend(msgs), [{"status": "ok"} for _ in msgs])[1])
    c = TestClient(app, base_url="https://testserver")
    c.post("/api/auth/start", json={"email": "maverick@example.in"}, headers=H)
    code = re.search(r"\b(\d{6})\b", otp.OUTBOX[-1][1]).group(1)
    tok = c.post("/api/auth/verify", json={"email": "maverick@example.in", "code": code, "client": "app"}).json()["token"]
    auth = {"Authorization": f"Bearer {tok}"}
    c.post("/api/onboarding/consent", json={"accept": True, "name": "Maverick"}, headers=auth)
    c.post("/api/onboarding/skip", headers=auth)
    c.post("/api/devices", json={"token": "ExponentPushToken[phone-agent-test]"}, headers=auth)
    yield c, auth, sent
    push.set_sender(None)
    llm.set_llm(None)


def _start(c, auth, goal="Book a sleeper bus from Pune to Aurangabad this Friday night, under ₹1,500", app_hint="redBus"):
    r = c.post("/api/phone/jobs", json={"goal": goal, "app": app_hint}, headers=auth)
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    assert c.get("/api/phone/jobs/next", headers=auth).json()["id"] == jid
    c.post(f"/api/phone/jobs/{jid}/event", json={"type": "started"}, headers=auth)
    return jid


def _step(c, auth, jid, screen, apps=None):
    r = c.post(f"/api/phone/jobs/{jid}/step", json={"screen": screen, "apps": apps}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def test_full_booking_runs_to_payment_and_hands_over(client):
    c, auth, sent = client
    fake = ScriptedLLM([
        {"thought": "Open redBus", "action": "open_app", "package": "in.redbus.android", "progress": "Opening redBus"},
        {"thought": "Fill origin", "action": "type", "node_id": 0, "text": "Pune", "progress": "Entering route"},
        {"thought": "Looks good, pay", "action": "tap", "node_id": 2, "progress": "Paying",
         "message": "Zingbus AC Sleeper, Fri 22:30, seat L4. Total ₹1,240."},
        {"thought": "Done", "action": "done", "message": "Booked", "progress": "Done"},
    ])
    llm.set_llm(fake)
    jid = _start(c, auth)
    assert _step(c, auth, jid, HOME, APPS) == {"action": "open_app", "package": "in.redbus.android", "progress": "Opening redBus"}
    out = _step(c, auth, jid, SEARCH)
    assert out["action"] == "type" and out["text"] == "Pune" and out["node_id"] == 0
    # The model tried to press "Proceed to pay": the server refuses and hands over to the user instead.
    out = _step(c, auth, jid, REVIEW)
    assert out["action"] == "need_user" and out["reason"] == "payment" and "₹1,240" in out["message"]
    job = c.get(f"/api/phone/jobs/{jid}", headers=auth).json()
    assert job["status"] == "waiting_user" and job["waiting_for"] == "payment"
    assert sent[-1]["data"]["kind"] == "phone_task" and "Ready for you to pay" in sent[-1]["body"]
    # The screen sent to the model is wrapped as untrusted data.
    assert "<untrusted>" in str(fake.extract_calls[-1][1])


def test_login_and_payment_apps_are_never_operated(client):
    c, auth, _ = client
    llm.set_llm(ScriptedLLM([]))
    jid = _start(c, auth)
    out = _step(c, auth, jid, LOGIN)
    assert out["action"] == "need_user" and out["reason"] == "login"
    c.post(f"/api/phone/jobs/{jid}/event", json={"type": "resumed"}, headers=auth)
    assert c.get(f"/api/phone/jobs/{jid}", headers=auth).json()["status"] == "running"
    out = _step(c, auth, jid, UPI)
    assert out["action"] == "need_user" and out["reason"] == "payment"


def test_unsafe_model_steps_are_neutralised(client):
    c, auth, _ = client
    llm.set_llm(ScriptedLLM([
        {"thought": "", "action": "type", "node_id": 1, "text": "hunter2", "progress": ""},          # password field
        {"thought": "", "action": "type", "node_id": 0, "text": "4111 1111 1111 1111", "progress": ""},  # card number
        {"thought": "", "action": "open_app", "package": "com.phonepe.app", "progress": ""},         # payment app
        {"thought": "", "action": "tap", "node_id": 99, "progress": ""},                              # no such element
    ]))
    jid = _start(c, auth)
    screen = {"package": "in.redbus.android", "nodes": [node(0, "Name", "EditText", edit=True),
                                                         node(1, "PIN", "EditText", edit=True)]}
    out = _step(c, auth, jid, screen, APPS)
    assert out["action"] == "wait"  # a field labelled PIN never gets typed into, even if not flagged as a password
    out = _step(c, auth, jid, screen)
    assert out["action"] == "wait"  # card numbers are never typed
    out = _step(c, auth, jid, screen)
    assert out["action"] == "wait"  # payment apps are never opened
    out = _step(c, auth, jid, SEARCH)
    assert out["action"] == "wait"  # unknown element


def test_stuck_detection_and_done(client):
    c, auth, sent = client
    llm.set_llm(ScriptedLLM([{"thought": "", "action": "tap", "node_id": 2, "progress": "Searching"}] * 3
                            + [{"thought": "", "action": "done", "message": "Cab booked: Ola Mini, ₹180 cash", "progress": ""}]))
    jid = _start(c, auth)
    for _ in range(3):
        assert _step(c, auth, jid, SEARCH)["action"] == "tap"
    out = _step(c, auth, jid, SEARCH)
    assert out["action"] == "need_user" and out["reason"] == "stuck"
    c.post(f"/api/phone/jobs/{jid}/event", json={"type": "resumed"}, headers=auth)
    out = _step(c, auth, jid, HOME)
    assert out["action"] == "done"
    job = c.get(f"/api/phone/jobs/{jid}", headers=auth).json()
    assert job["status"] == "done" and "Ola Mini" in job["result"]
    assert _step(c, auth, jid, HOME)["action"] == "stop"


def test_stop_and_secret_goals(client):
    c, auth, _ = client
    llm.set_llm(ScriptedLLM([]))
    jid = _start(c, auth)
    c.post(f"/api/phone/jobs/{jid}/event", json={"type": "stopped"}, headers=auth)
    assert _step(c, auth, jid, HOME)["action"] == "stop"
    r = c.post("/api/phone/jobs", json={"goal": "Pay with card 4111 1111 1111 1111 on Swiggy"}, headers=auth)
    assert r.status_code == 400


def test_chat_proposal_approval_queues_the_job(client):
    c, auth, _ = client
    with session_scope() as s:
        user = s.scalar(select(User).where(User.email == "maverick@example.in"))
        a = actions.propose(s, user, "phone_task", {"goal": "Book Tatkal 3A Mumbai to Aurangabad on Saturday", "app": "IRCTC"},
                            "On your phone in IRCTC: Book Tatkal 3A", "chat")
        aid = a.id
    r = c.post(f"/api/approvals/{aid}/approve", headers=auth)
    assert r.status_code == 200 and "Starting on your phone" in r.json()["result"]
    nxt = c.get("/api/phone/jobs/next", headers=auth).json()
    assert nxt["app_hint"] == "IRCTC" and "Tatkal" in nxt["goal"]
    with session_scope() as s:
        assert s.get(Action, aid).status == "executed"
        assert s.scalar(select(PhoneJob)).action_id == aid
