"""End to end: a new user texts in, connects Google, gets their dropped threads, approves a reply."""
import re
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.channels import InboundMessage
from app.db import session_scope
from app.main import app, process_message
from app.models import Action, Commitment, Consent, Event, Person, User
from tests.fakes import now

PHONE = "+919876543210"
_n = 0


def text(body, name="Maverick"):
    global _n
    _n += 1
    process_message(InboundMessage(phone=PHONE, text=body, external_id=f"wamid.{_n}", profile_name=name), "console")


def last(channel):
    return channel.sent[-1][1]


def seed_mailbox(g):
    t = now()
    g.add_email("m0", "t0", "me@example.com", ["ravi@distrib.com"], "Order", "Hi Ravi, order confirmed. Thanks, Maverick", t - timedelta(days=20), sent=True)
    g.add_email("m1", "t1", "ravi@distrib.com", ["me@example.com"], "GST invoice",
                "Hi, can you send the revised GST invoice by Friday? Thanks", t - timedelta(days=4), from_name="Ravi Kumar")
    g.add_email("m2", "t2", "anika@vc.com", ["me@example.com"], "Deck", "Looking forward to the deck.", t - timedelta(days=4), from_name="Anika")
    g.add_email("m3", "t2", "me@example.com", ["anika@vc.com"], "Re: Deck", "I'll send the deck by Monday.", t - timedelta(days=3), sent=True)
    g.add_email("m4", "t3", "news@shop.com", ["me@example.com"], "Big sale", "50% off everything", t - timedelta(days=1), newsletter=True)
    g.add_email("m5", "t4", "sales@newvendor.com", ["me@example.com"], "Quote", "We'll share the quote by Wednesday.", t - timedelta(days=5), from_name="Priya")
    g.add_event("e1", "Investor call", t.replace(hour=10, minute=0) if t.hour < 10 else t + timedelta(hours=1), attendees=["anika@vc.com"])


def scripted_extraction(content):
    out = []
    if 'thread id="t1"' in content:
        out.append({"thread_id": "t1", "direction": "user_owes", "description": "Send Ravi the revised GST invoice",
                    "counterparty_email": "ravi@distrib.com", "counterparty_name": "Ravi Kumar", "due_date": None, "confidence": 0.9})
    if 'thread id="t2"' in content:
        out.append({"thread_id": "t2", "direction": "user_owes", "description": "Send Anika the deck",
                    "counterparty_email": "anika@vc.com", "counterparty_name": "Anika", "due_date": None, "confidence": 0.9,
                    "project": "Seed round"})
    if 'thread id="t4"' in content:
        out.append({"thread_id": "t4", "direction": "owed_to_user", "description": "Priya to share the quote",
                    "counterparty_email": "sales@newvendor.com", "counterparty_name": "Priya", "due_date": None, "confidence": 0.8})
    return {"commitments": out, "fulfilled_commitment_ids": [], "relationships": [{"email": "anika@vc.com", "relationship": "investor"}]}


def scripted_draft(content):
    if "ravi@distrib.com" in content:
        return {"kind": "reply", "subject": "GST invoice", "body": "Hi Ravi, sending the revised invoice today. Thanks, Maverick"}
    if "anika@vc.com" in content:
        return {"kind": "reminder", "reminder_text": "Send Anika the deck you promised for Monday"}
    return {"kind": "nudge", "subject": "Quote", "body": "Hi Priya, any update on the quote? Thanks"}


def test_new_user_to_first_sent_reply(channel, fake_google, fake_llm):
    seed_mailbox(fake_google)
    fake_llm.extractors = {
        "record_commitments": scripted_extraction,
        "draft": scripted_draft,
        "voice_profile": lambda c: {"profile": "Short, friendly, signs off 'Thanks, Maverick'."},
    }

    # 1. First contact: welcome + consent ask, time zone guessed from the +91 number
    text("hi")
    assert "Reply *YES*" in last(channel)
    with session_scope() as s:
        user = s.scalar(select(User).where(User.phone == PHONE))
        assert user.timezone == "Asia/Kolkata"
        assert user.name == "Maverick"

    # 2. Consent -> Google link
    text("yes")
    link = re.search(r"https://assistant\.test/connect/google\?s=(\S+)", last(channel))
    assert link, last(channel)

    # 3. Link redirects to Google consent with offline access
    client = TestClient(app)
    r = client.get(f"/connect/google?s={link.group(1)}", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "accounts.google.com" in r.headers["location"] and "access_type=offline" in r.headers["location"]

    # 4. OAuth callback -> background first sync -> "here's what looks open"
    r = client.get(f"/oauth/google/callback?state={link.group(1)}&code=abc")
    assert r.status_code == 200 and "connected" in r.text.lower()
    joined = "\n".join(t for _, t in channel.sent)
    assert "Here's what looks open" in joined
    assert "Investor call" in joined

    with session_scope() as s:
        user = s.scalar(select(User).where(User.phone == PHONE))
        assert user.onboarding_state == "active"
        assert {c.scope for c in s.scalars(select(Consent).where(Consent.user_id == user.id))} >= {"terms", "gmail", "calendar"}
        # newsletter skipped, people learned
        assert s.scalar(select(Event).where(Event.external_id == "m4")) is None
        anika = s.scalar(select(Person).where(Person.email == "anika@vc.com"))
        assert anika.relationship_note == "investor"
        loops = s.scalars(select(Commitment).where(Commitment.user_id == user.id)).all()
        assert len(loops) == 3
        acts = {a.payload.get("to", [None])[0] if a.kind == "send_email" else "note": a
                for a in s.scalars(select(Action).where(Action.user_id == user.id))}
        ravi_action = acts["ravi@distrib.com"]
        vendor_action = acts["sales@newvendor.com"]
        assert ravi_action.tier == 2  # user has written to Ravi before
        assert vendor_action.tier == 3  # never written to this vendor: always preview
        assert acts["note"].kind == "note"
        ravi_no, ravi_loop = ravi_action.number, ravi_action.commitment_id

    # Nothing was sent without approval
    assert fake_google.sent == []

    # 5. Approve the Ravi reply by number
    text(str(ravi_no))
    assert last(channel) == "Sent to ravi@distrib.com."
    assert len(fake_google.sent) == 1
    sent = fake_google.sent[0]
    assert sent["to"] == "ravi@distrib.com"
    assert sent["subject"] == "Re: GST invoice"
    assert sent["thread_id"] == "t1"
    assert sent["in_reply_to"] == "<m1@mail.example.com>"
    with session_scope() as s:
        assert s.get(Commitment, ravi_loop).status == "done"

    # 6. The audit log is readable in chat
    text("what did you do today")
    assert "Did: Sent to ravi@distrib.com" in last(channel)


def test_duplicate_webhook_delivery_is_ignored(channel, fake_google, fake_llm):
    msg = InboundMessage(phone=PHONE, text="hi", external_id="wamid.dup", profile_name="M")
    process_message(msg, "console")
    process_message(msg, "console")
    assert len(channel.sent) == 1


def test_webhook_verification_and_signature(monkeypatch, channel, fake_llm):
    import hashlib
    import hmac
    import json

    from app.config import get_settings

    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "vt")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "appsecret")
    monkeypatch.setenv("ENV", "prod")
    get_settings.cache_clear()
    client = TestClient(app)

    r = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"})
    assert r.status_code == 200 and r.text == "42"
    assert client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "no"}).status_code == 403

    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "919876543210", "id": "wamid.sig", "type": "text", "text": {"body": "hi"}}]}}]}]}
    body = json.dumps(payload).encode()
    assert client.post("/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": "sha256=bad"}).status_code == 401
    sig = "sha256=" + hmac.new(b"appsecret", body, hashlib.sha256).hexdigest()
    r = client.post("/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sig, "content-type": "application/json"})
    assert r.status_code == 200
    assert "Reply *YES*" in last(channel)  # processed in the background task
    assert client.post("/dev/simulate", json={"phone": "1", "text": "x"}).status_code == 404  # simulator off in prod
