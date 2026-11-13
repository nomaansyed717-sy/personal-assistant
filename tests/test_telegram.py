"""Telegram: link from the app, chat there, approve with buttons, and get proactive messages mirrored."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent import actions
from app.channels import telegram
from app.config import get_settings
from app.db import session_scope
from app.main import app
from app.messenger import send
from app.models import Action, User
from tests.test_app import H, _app_client

SECRET = "tg-secret-123"


@pytest.fixture
def tg(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "AideTestBot")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        calls.append((method, json.loads(request.content or b"{}")))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(calls)}})

    telegram._transport = httpx.MockTransport(handler)
    yield calls
    telegram._transport = None
    get_settings.cache_clear()


def _hook(c: TestClient, update: dict, secret: str = SECRET):
    return c.post("/webhooks/telegram", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": secret})


def _msg(chat: int, text: str, mid: int = 1) -> dict:
    return {"update_id": mid, "message": {"message_id": mid, "chat": {"id": chat, "type": "private"},
                                          "from": {"username": "maverick"}, "text": text}}


def _sent(calls, method="sendMessage"):
    return [p for m, p in calls if m == method]


def test_link_chat_and_approve_with_buttons(tg):
    c, auth = _app_client("tele@example.in")
    me = c.get("/api/me", headers=auth).json()["telegram"]
    assert me == {"available": True, "linked": False, "username": None, "notify": True}
    url = c.post("/api/telegram/link", headers={**auth, **H}).json()["url"]
    assert url.startswith("https://t.me/AideTestBot?start=")
    code = url.split("start=")[1]

    assert _hook(c, _msg(555, f"/start {code}"), secret="wrong").status_code == 403
    assert _hook(c, _msg(555, f"/start {code}")).json()["ok"]
    assert "Linked to your Aide account" in _sent(tg)[-1]["text"]
    assert c.get("/api/me", headers=auth).json()["telegram"]["linked"] is True
    # The link can't be reused by someone else.
    _hook(c, _msg(777, f"/start {code}", 2))
    with session_scope() as s:
        assert s.scalar(select(User).where(User.email == "tele@example.in")).telegram_chat_id == "555"

    # A proactive message with a proposal is mirrored with Approve / Skip buttons.
    with session_scope() as s:
        user = s.scalar(select(User).where(User.email == "tele@example.in"))
        user.onboarding_state = "active"
        a = actions.propose(s, user, "note", {}, "Chase Priya for the quote")
        send(s, user, f"*{a.number}.* Chase Priya for the quote\n\nReply *{a.number}* to go ahead")
    last = _sent(tg)[-1]
    assert last["chat_id"] == "555" and last["parse_mode"] == "HTML" and "<b>1.</b>" in last["text"]
    assert last["reply_markup"]["inline_keyboard"][0][1]["callback_data"] == "skip:1"

    # Tapping Skip runs "skip 1" for the linked user.
    _hook(c, {"update_id": 9, "callback_query": {"id": "cb1", "data": "skip:1",
                                                 "message": {"chat": {"id": 555, "type": "private"}}}})
    assert any(m == "answerCallbackQuery" for m, _ in tg)
    with session_scope() as s:
        assert s.scalar(select(Action)).status == "rejected"

    # Unlinking from the app stops the mirror.
    assert c.delete("/api/telegram", headers={**auth, **H}).json()["ok"]
    assert c.get("/api/me", headers=auth).json()["telegram"]["linked"] is False


def test_unknown_chat_gets_instructions_and_groups_are_ignored(tg):
    c = TestClient(app)
    _hook(c, _msg(999, "hello"))
    assert "Connect Telegram" in _sent(tg)[-1]["text"]
    n = len(tg)
    group = _msg(1000, "hello")
    group["message"]["chat"]["type"] = "group"
    _hook(c, group)
    assert len(tg) == n


def test_html_formatting_is_escaped():
    assert telegram.to_html("*Today* <b>x</b> & _soon_") == "<b>Today</b> &lt;b&gt;x&lt;/b&gt; &amp; <i>soon</i>"
    assert telegram._buttons("no proposals here") is None


def test_link_needs_telegram_configured():
    c, auth = _app_client("tele2@example.in")
    r = c.post("/api/telegram/link", headers={**auth, **H})
    assert r.status_code == 400 and "isn't switched on" in r.json()["detail"]
