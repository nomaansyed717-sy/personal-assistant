"""Muse-parity features: persona, memory, goals and ideas, standing tasks, skills, Sentinel, research,
vault, purchases, media, migrations."""
import socket
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text

from app import ideas, research, skills, standing, vault
from app.agent import actions
from app.agent.agent import _system, run_background
from app.agent.router import route
from app.context import memory
from app.db import get_engine, session_scope, utcnow
from app.models import Action, Goal, StandingTask, User
from app.sentinel import check_url, contains_secret
from tests.fakes import FakeLLM
from tests.helpers import PHONE, make_active_user


def _u(s, uid):
    return s.get(User, uid)


# ---------------------------------------------------------------- persona


def test_name_and_persona_shape_the_agent(channel, fake_llm):
    uid = make_active_user()
    with session_scope() as s:
        assert route(s, _u(s, uid), "call yourself Pumpkin", fake_llm) == "Love it. I'm Pumpkin from now on."
        _u(s, uid).persona = "Warm and a little witty"
        prompt = _system(s, _u(s, uid))
        assert prompt.startswith("You are Pumpkin, Sam Lee's personal AI agent")
        assert "Warm and a little witty" in prompt


# ---------------------------------------------------------------- memory


def test_memory_learns_lists_and_forgets(channel, fake_llm):
    uid = make_active_user()
    fake_llm.extractors["remember"] = lambda c: {"memories": ["Prefers aisle seats on flights.", "Card 4111 1111 1111 1111"]}
    fake_llm.turns = [FakeLLM.say("Noted.")]
    with session_scope() as s:
        from app.messenger import record_inbound

        u = _u(s, uid)
        record_inbound(s, u, "I always want an aisle seat when I fly, remember that", "m1", "console")
        route(s, u, "I always want an aisle seat when I fly, remember that", fake_llm)
        texts = [t for _, t in memory.all_memories(s, u)]
        assert texts == ["Prefers aisle seats on flights."]  # the card number was refused
        assert "aisle seats" in route(s, u, "what do you remember", fake_llm)
        assert "Forgotten 1 memory" in route(s, u, "forget aisle", fake_llm)
        assert memory.all_memories(s, u) == []


# ---------------------------------------------------------------- goals and ideas


def test_ideas_compose_from_goals(fake_llm):
    uid = make_active_user()
    fake_llm.extractors["suggest_ideas"] = lambda c: {"ideas": [{"idea": "Book two Pune site visits this week", "goal": "Pune store"}]}
    with session_scope() as s:
        s.add(Goal(user_id=uid, title="Open the Pune store by December"))
        s.flush()
        msg = ideas.compose(s, _u(s, uid), fake_llm)
        assert "Book two Pune site visits" in msg and "do idea 2" in msg
        name, content = fake_llm.extract_calls[-1]
        assert "Open the Pune store" in content


def test_no_ideas_without_goals_or_memories(fake_llm):
    uid = make_active_user()
    with session_scope() as s:
        assert ideas.compose(s, _u(s, uid), fake_llm) is None


# ---------------------------------------------------------------- standing tasks


def test_schedule_parsing_and_next_run():
    base = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)  # 09:30 in Kolkata, a Monday
    assert standing.next_run("daily 09:00", "Asia/Kolkata", base) == datetime(2026, 10, 6, 3, 30, tzinfo=UTC)
    assert standing.next_run("daily 10:00", "Asia/Kolkata", base) == datetime(2026, 10, 5, 4, 30, tzinfo=UTC)
    assert standing.next_run("weekly fri 16:00", "Asia/Kolkata", base) == datetime(2026, 10, 9, 10, 30, tzinfo=UTC)
    assert standing.next_run("every 6h", "UTC", base) == base + timedelta(hours=6)
    assert standing.next_run("once 2026-10-01T10:00", "UTC", base) is None
    with pytest.raises(standing.ScheduleError):
        standing.normalize("every 5m")
    with pytest.raises(standing.ScheduleError):
        standing.normalize("whenever")


def test_standing_tasks_run_and_only_message_when_useful(channel, fake_llm):
    uid = make_active_user()
    with session_scope() as s:
        quiet = standing.create(s, _u(s, uid), "Price watch", "check price", "every 6h")
        loud = standing.create(s, _u(s, uid), "Visa slots", "check slots", "once 2099-01-01T09:00")
        quiet.next_run_at = loud.next_run_at = utcnow() - timedelta(minutes=1)
    answers = {"Price watch": "NOTHING_NEW", "Visa slots": "A slot opened on 14 Oct at 10:00."}
    with session_scope() as s:
        n = standing.run_due(s, lambda sess, user, t: answers[t.title])
        assert n == 2
    with session_scope() as s:
        rows = {t.title: t for t in s.scalars(select(StandingTask)).all()}
        assert rows["Price watch"].status == "active" and rows["Price watch"].runs == 1
        assert rows["Visa slots"].status == "done"
    sent = [t for _, t in channel.sent]
    assert any("Visa slots" in t and "14 Oct" in t for t in sent)
    assert not any("Price watch" in t for t in sent)


def test_agent_creates_task_and_runs_it_in_background(channel, fake_llm):
    uid = make_active_user()
    fake_llm.turns = [
        FakeLLM.tool("create_task", {"title": "Chase invoices", "instruction": "Run invoice-chaser. Else NOTHING_NEW",
                                     "schedule": "weekly fri 16:00"}),
        FakeLLM.say("Every Friday at 4pm I'll chase unpaid invoices."),
        # background run
        FakeLLM.tool("use_skill", {"name": "invoice-chaser"}),
        FakeLLM.say("NOTHING_NEW"),
    ]
    with session_scope() as s:
        from app.messenger import record_inbound

        u = _u(s, uid)
        record_inbound(s, u, "chase my unpaid invoices every friday", "m1", "console")
        assert "Every Friday" in route(s, u, "chase my unpaid invoices every friday", fake_llm)
        t = s.scalar(select(StandingTask))
        assert t.schedule == "weekly fri 16:00"
        out = run_background(s, u, t.instruction, fake_llm)
        assert out == "NOTHING_NEW"
        skill_result = fake_llm.complete_calls[-1][-1]["content"][0]["content"]
        assert skill_result.startswith("SKILL invoice-chaser")


# ---------------------------------------------------------------- skills


def test_builtin_and_user_skills(fake_llm):
    uid = make_active_user()
    with session_scope() as s:
        u = _u(s, uid)
        names = {x["name"] for x in skills.all_skills(s, u)}
        assert {"inbox-triage", "invoice-chaser", "lead-reply", "price-watch", "subscription-audit"} <= names
        skills.create(s, u, "Vendor Reorder", "Reorder stock", "1. search low stock emails 2. draft orders")
        assert skills.get(s, u, "vendor reorder")["instructions"].startswith("1. search")
        assert skills.create(s, u, "inbox-triage", "mine", "custom steps here").name == "my-inbox-triage"


# ---------------------------------------------------------------- Sentinel


def test_sentinel_blocks_internal_urls_and_secrets(monkeypatch):
    assert not check_url("file:///etc/passwd").allowed
    assert not check_url("http://localhost:8080/admin").allowed
    assert not check_url("http://127.0.0.1/").allowed
    assert not check_url("http://169.254.169.254/latest/meta-data").allowed
    assert not check_url("http://10.0.0.5/").allowed
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    assert check_url("https://example.com/page").allowed
    assert contains_secret("my card is 4111 1111 1111 1111")
    assert contains_secret("your OTP is 482913")
    assert not contains_secret("see you at 10:30 tomorrow")


def test_sentinel_reviewer_can_block_an_approved_action(channel, fake_google):
    uid = make_active_user()
    llm = FakeLLM()
    llm.extractors["sentinel_review"] = lambda c: {"verdict": "block", "reason": "the user never asked to email this person"}
    with session_scope() as s:
        a = actions.propose(s, _u(s, uid), "send_email", {"to": ["ravi@distrib.com"], "subject": "x", "body": "y"}, "E")
        out = actions.execute(s, _u(s, uid), a, llm=llm)
        assert out.startswith("Sentinel stopped this email") and a.status == "blocked"
    assert fake_google.sent == []


def test_sentinel_rule_blocks_secret_in_outbound_email(channel, fake_google):
    uid = make_active_user()
    with session_scope() as s:
        a = actions.propose(s, _u(s, uid), "send_email",
                            {"to": ["ravi@distrib.com"], "subject": "code", "body": "Here's my OTP 123456"}, "E")
        out = actions.execute(s, _u(s, uid), a, llm=FakeLLM())
        assert "Sentinel stopped" in out
    assert fake_google.sent == []


# ---------------------------------------------------------------- research


def test_read_url_follows_safe_redirects_and_blocks_private(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, *a, **k: [(2, 1, 6, "", ("10.0.0.9" if host == "intranet.example" else "93.184.216.34", 80))])

    def handler(req: httpx.Request):
        if req.url.host == "shop.example" and req.url.path == "/p":
            return httpx.Response(301, headers={"location": "https://shop.example/product"})
        if req.url.path == "/product":
            return httpx.Response(200, headers={"content-type": "text/html"},
                                  text="<html><title>Kettle</title><body><h1>Steel kettle</h1><p>Rs 1,299</p></body></html>")
        if req.url.path == "/leak":
            return httpx.Response(302, headers={"location": "http://intranet.example/secrets"})
        return httpx.Response(404)

    research.set_http(httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        page = research.read("https://shop.example/p")
        assert page["title"] == "Kettle" and "Rs 1,299" in page["text"]
        with pytest.raises(research.ResearchError, match="Sentinel"):
            research.read("https://shop.example/leak")
    finally:
        research.set_http(None)


# ---------------------------------------------------------------- vault and purchases


def test_vault_never_exposes_secrets(fake_llm):
    uid = make_active_user()
    with session_scope() as s:
        u = _u(s, uid)
        vault.add(s, u, "Amazon", "https://www.amazon.in/", "sam@example.com", "hunter2")
        listing = vault.listing(s, u)
        assert listing == [{"id": listing[0]["id"], "label": "Amazon", "site": "amazon.in"}]
        assert vault.credentials_for(s, u, "https://www.amazon.in/ap/signin") == ("sam@example.com", "hunter2")
        assert vault.credentials_for(s, u, "https://evil-amazon.in.attacker.com") is None
        from app.agent.tools import ToolContext

        assert "hunter2" not in ToolContext(s, u).run("list_logins", {})


def test_purchase_is_tier_4_and_ends_in_checkout_handoff(channel, fake_llm, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    uid = make_active_user()
    with session_scope() as s:
        from app.agent.tools import ToolContext

        ctx = ToolContext(s, _u(s, uid))
        ctx.run("propose_purchase", {"item": "Steel kettle", "url": "https://shop.example/product", "price": "Rs 1,299"})
        a = s.scalar(select(Action))
        assert a.kind == "purchase" and a.tier == 4 and a.status == "proposed"
        assert actions.delegate(s, _u(s, uid), "purchase").startswith("That kind of action always needs your yes")
    with session_scope() as s:
        out = route(s, _u(s, uid), "1", fake_llm)
        assert out.startswith("Ready for you to check out: Steel kettle for Rs 1,299") and "https://shop.example/product" in out


# ---------------------------------------------------------------- media


def test_photo_goes_to_the_agent_and_voice_needs_a_key(channel, fake_llm):
    from app.channels import InboundMessage
    from app.main import process_message

    make_active_user()
    channel.media["img1"] = (b"\x89PNG fake", "image/png")
    channel.media["aud1"] = (b"OggS", "audio/ogg")
    fake_llm.turns = [FakeLLM.say("That's a restaurant bill for Rs 2,340. Want me to log it?")]
    process_message(InboundMessage(phone=PHONE, text="split this", external_id="p1", kind="image", media_id="img1",
                                   mime="image/png"), "console")
    assert "restaurant bill" in channel.sent[-1][1]
    last_user_turn = fake_llm.complete_calls[0][-1]["content"]
    assert last_user_turn[0]["type"] == "image" and last_user_turn[0]["source"]["media_type"] == "image/png"
    process_message(InboundMessage(phone=PHONE, text="", external_id="p2", kind="audio", media_id="aud1",
                                   mime="audio/ogg"), "console")
    assert "Voice notes need transcription" in channel.sent[-1][1]


# ---------------------------------------------------------------- planned view + migrations


def test_planned_view_lists_waiting_and_tasks(channel, fake_llm):
    uid = make_active_user()
    with session_scope() as s:
        actions.propose(s, _u(s, uid), "send_email", {"to": ["ravi@distrib.com"], "subject": "x", "body": "y"},
                        "Email Ravi about the invoice")
        standing.create(s, _u(s, uid), "Price watch", "check", "every 12h")
    with session_scope() as s:
        out = route(s, _u(s, uid), "what are you planning?", fake_llm)
        assert "Waiting for your yes" in out and "#1 Email Ravi" in out and "Price watch" in out


def test_migration_adds_missing_columns():
    from app.migrate import add_missing_columns

    make_active_user()
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text('ALTER TABLE users DROP COLUMN persona'))
        conn.execute(text('ALTER TABLE users DROP COLUMN ideas_enabled'))
    added = add_missing_columns(eng)
    assert set(added) == {"users.persona", "users.ideas_enabled"}
    with session_scope() as s:
        u = s.scalar(select(User))
        assert u.ideas_enabled is True and u.persona is None
