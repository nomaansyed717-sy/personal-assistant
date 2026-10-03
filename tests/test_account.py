"""User data controls, the WhatsApp 24h window, retention, and settings commands."""
from datetime import timedelta

from sqlalchemy import func, select

from app.agent.account import purge_raw
from app.agent.router import route
from app.channels import InboundMessage
from app.crypto import encrypt
from app.db import session_scope, utcnow
from app.main import process_message
from app.messenger import send
from app.models import Commitment, Event, Message, Person, User
from tests.helpers import PHONE, make_active_user


def test_delete_everything_needs_exact_confirmation(channel, fake_google, fake_llm):
    uid = make_active_user()
    process_message(InboundMessage(phone=PHONE, text="delete everything", external_id="a1"), "console")
    assert "Reply *DELETE*" in channel.sent[-1][1]
    process_message(InboundMessage(phone=PHONE, text="delete", external_id="a2"), "console")
    assert channel.sent[-1][1] == "Okay, nothing was deleted."
    process_message(InboundMessage(phone=PHONE, text="delete everything", external_id="a3"), "console")
    process_message(InboundMessage(phone=PHONE, text="DELETE", external_id="a4"), "console")
    assert "Everything is deleted" in channel.sent[-1][1]
    assert fake_google.revoked == ["rt-old"]
    with session_scope() as s:
        assert s.get(User, uid) is None
        assert s.scalar(select(func.count()).select_from(Message)) == 0
        assert s.scalar(select(func.count()).select_from(Person)) == 0


def test_what_do_you_know_and_forget(channel, fake_llm):
    uid = make_active_user()
    with session_scope() as s:
        p = s.scalar(select(Person).where(Person.email == "ravi@distrib.com"))
        s.add(Commitment(user_id=uid, direction="user_owes", description="Send Ravi the invoice", person_id=p.id))
    with session_scope() as s:
        out = route(s, s.get(User, uid), "what do you know about ravi?", fake_llm)
        assert "You owe: Send Ravi the invoice" in out
        out = route(s, s.get(User, uid), "forget ravi@distrib.com", fake_llm)
        assert "Forgotten" in out
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Commitment)) == 0
        out = route(s, s.get(User, uid), "what do you know", fake_llm)
        assert "Open loops I'm tracking: 0" in out


def test_window_closed_queues_and_sends_template(channel, fake_llm):
    import app.channels.base as base

    class WindowChannel(base.ConsoleChannel):
        has_session_window = True

    from app import channels

    ch = WindowChannel()
    channels.set_channel(ch)
    uid = make_active_user(last_inbound_hours_ago=30)
    with session_scope() as s:
        u = s.get(User, uid)
        send(s, u, "Your brief: 3 things")
        send(s, u, "Second message")
    assert len(ch.sent) == 1 and ch.sent[0][1].startswith("[template:")
    # The user's reply reopens the window and delivers the queue, in order.
    process_message(InboundMessage(phone=PHONE, text="what did you do today", external_id="r1"), "console")
    texts = [t for _, t in ch.sent[1:]]
    assert texts[0] == "Your brief: 3 things" and texts[1] == "Second message"
    channels.set_channel(None)


def test_retention_purges_raw_text_but_keeps_facts():
    uid = make_active_user()
    with session_scope() as s:
        s.add(Event(user_id=uid, source="gmail", external_id="old", kind="email_in", occurred_at=utcnow() - timedelta(days=120),
                    body_enc=encrypt(uid, "old body"), processed=True))
        s.add(Event(user_id=uid, source="gmail", external_id="new", kind="email_in", occurred_at=utcnow(),
                    body_enc=encrypt(uid, "new body"), processed=True))
    with session_scope() as s:
        assert purge_raw(s, 90) == 1
    with session_scope() as s:
        old = s.scalar(select(Event).where(Event.external_id == "old"))
        new = s.scalar(select(Event).where(Event.external_id == "new"))
        assert old.body_enc is None and old.purged and new.body_enc is not None


def test_settings_commands(channel, fake_llm):
    uid = make_active_user()
    with session_scope() as s:
        u = s.get(User, uid)
        assert "Europe/London" in route(s, u, "timezone Europe/London", fake_llm)
        assert "don't recognise" in route(s, u, "timezone Mars/Olympus", fake_llm)
        assert "07:00" in route(s, u, "brief at 7am", fake_llm)
        assert "19:00" in route(s, u, "brief at 7pm", fake_llm)
        assert "Paused" in route(s, u, "stop", fake_llm)
        assert u.paused
        route(s, u, "resume", fake_llm)
        assert not u.paused


def test_encrypted_at_rest():
    uid = make_active_user()
    with session_scope() as s:
        s.add(Message(user_id=uid, direction="in", body_enc=encrypt(uid, "my secret plan")))
    with session_scope() as s:
        raw = s.scalar(select(Message.body_enc))
        assert "secret" not in raw
