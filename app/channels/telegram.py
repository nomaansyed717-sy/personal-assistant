"""Telegram: a second way to talk to Aide, linked to an existing account from the app.

Linking: the app asks for a one-time link (t.me/<bot>?start=<code>); the user taps Start in Telegram and the bot
ties that chat to their account. After that, messages in Telegram go to the assistant like app messages, replies
come back there and into the app inbox, and proactive messages (briefs, results, approvals) are mirrored to the
chat with Approve / Skip buttons. Telegram's Bot API allows AI assistants, unlike WhatsApp Business since 2026.

Inbound updates are checked with the secret token Telegram echoes in X-Telegram-Bot-Api-Secret-Token.
"""
import html
import logging
import re
import secrets
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.messenger import split_message
from app.models import OAuthState, User
from app.util import aware

log = logging.getLogger(__name__)
MAX_LEN = 4000
LINK_MINUTES = 15
_transport: httpx.BaseTransport | None = None  # tests swap in a MockTransport


def enabled() -> bool:
    return bool(get_settings().telegram_bot_token)


def _api(method: str, **payload):
    s = get_settings()
    with httpx.Client(timeout=30, transport=_transport) as http:
        r = http.post(f"https://api.telegram.org/bot{s.telegram_bot_token}/{method}", json=payload)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not data.get("ok"):
        log.warning("telegram %s failed: %s", method, str(data)[:200])
    return data.get("result")


def to_html(text: str) -> str:
    """Our messages use WhatsApp-style *bold* and _italic_; Telegram gets the same as HTML."""
    out = html.escape(text, quote=False)
    out = re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", out)
    return re.sub(r"(?<![\w/])_([^_\n]+)_(?![\w/])", r"<i>\1</i>", out)


def _buttons(text: str) -> dict | None:
    """Approve / Skip buttons for each numbered proposal in the message ("*2.* Send Ravi …")."""
    nums = list(dict.fromkeys(int(n) for n in re.findall(r"^\*(\d+)\.\*", text, flags=re.M)))[:5]
    if not nums:
        return None
    return {"inline_keyboard": [[{"text": f"Approve {n}", "callback_data": f"yes:{n}"},
                                 {"text": f"Skip {n}", "callback_data": f"skip:{n}"}] for n in nums]}


def send(chat_id: str, text: str) -> None:
    parts = split_message(text, MAX_LEN)
    for i, part in enumerate(parts):
        payload = {"chat_id": chat_id, "text": to_html(part), "parse_mode": "HTML", "disable_web_page_preview": True}
        if i == len(parts) - 1 and (kb := _buttons(text)):
            payload["reply_markup"] = kb
        _api("sendMessage", **payload)


def mirror(user: User, text: str) -> None:
    """Copy a proactive message to the user's linked Telegram chat."""
    if enabled() and user.telegram_chat_id and user.telegram_notify:
        try:
            send(user.telegram_chat_id, text)
        except httpx.HTTPError:
            log.warning("telegram mirror failed for user %s", user.id)


# ------------------------------------------------------------------ linking


def link_url(session: Session, user: User) -> str:
    s = get_settings()
    if not enabled() or not s.telegram_bot_username:
        raise ValueError("Telegram isn't switched on for this server yet")
    code = "L" + secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:24]
    session.add(OAuthState(token=code, user_id=user.id, return_to="telegram"))
    return f"https://t.me/{s.telegram_bot_username}?start={code}"


def _link(session: Session, chat_id: str, username: str | None, code: str) -> User | None:
    st = session.scalar(select(OAuthState).where(OAuthState.token == code, OAuthState.return_to == "telegram"))
    if not st or st.used or utcnow() - aware(st.created_at) > timedelta(minutes=LINK_MINUTES):
        return None
    st.used = True
    other = session.scalar(select(User).where(User.telegram_chat_id == chat_id))
    if other:
        other.telegram_chat_id = None  # this chat moves to the new account
    user = session.get(User, st.user_id)
    user.telegram_chat_id, user.telegram_username, user.telegram_notify = chat_id, username, True
    return user


# ------------------------------------------------------------------ inbound


def verify(secret_header: str | None) -> bool:
    want = get_settings().telegram_webhook_secret
    return bool(want) and secrets.compare_digest(secret_header or "", want)


def handle_update(session: Session, update: dict, llm) -> None:
    """Process one Telegram update: link, a message, or a button tap."""
    from app.agent.router import route
    from app.crypto import encrypt
    from app.messenger import record_inbound
    from app.models import Message

    if cb := update.get("callback_query"):
        chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
        _api("answerCallbackQuery", callback_query_id=cb.get("id"))
        kind, _, num = (cb.get("data") or "").partition(":")
        text = num if kind == "yes" else f"skip {num}" if kind == "skip" else ""
        msg_id = f"tg-cb-{cb.get('id')}"
    elif msg := update.get("message"):
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if msg.get("chat", {}).get("type") != "private":
            return  # only one-to-one chats
        text = (msg.get("text") or msg.get("caption") or "").strip()
        msg_id = f"tg-{chat_id}-{msg.get('message_id')}"
        if text.startswith("/start"):
            code = text.split(maxsplit=1)[1] if " " in text else ""
            user = _link(session, chat_id, (msg.get("from") or {}).get("username"), code) if code else None
            if user:
                send(chat_id, f"Linked to your {get_settings().app_name} account. Message me here any time; "
                              "I'll also send your brief and anything that needs your yes.")
            elif not session.scalar(select(User).where(User.telegram_chat_id == chat_id)):
                send(chat_id, f"Hi! To use {get_settings().app_name} here, open the app > More > Settings > "
                              "Connect Telegram, and tap the link it gives you.")
            return
    else:
        return
    user = session.scalar(select(User).where(User.telegram_chat_id == chat_id))
    if user is None:
        send(chat_id, f"This chat isn't linked yet. Open the {get_settings().app_name} app > More > Settings > Connect Telegram.")
        return
    if text in ("/stop", "/unlink"):
        user.telegram_chat_id = None
        send(chat_id, "Unlinked. You can link again from the app.")
        return
    attachments: list[dict] = []
    msg = update.get("message") or {}
    file_id = ((msg.get("voice") or msg.get("audio") or {}).get("file_id")
               or (msg.get("photo") or [{}])[-1].get("file_id") or (msg.get("document") or {}).get("file_id"))
    if file_id:
        from app.media import MediaError, prepare_bytes

        try:
            data, mime = download(file_id, msg)
            text, attachments = prepare_bytes(data, mime, text, (msg.get("document") or {}).get("file_name"),
                                              audio=bool(msg.get("voice") or msg.get("audio")),
                                              language=user.voice_language or "auto")
        except (MediaError, httpx.HTTPError) as exc:
            send(chat_id, str(exc) if isinstance(exc, MediaError) else "I couldn't download that file. Please try again.")
            return
    if not text:
        return
    if not record_inbound(session, user, text, msg_id, "telegram"):
        return  # Telegram redelivered an update we already handled
    reply = route(session, user, text, llm, attachments) or ""
    if reply:
        session.add(Message(user_id=user.id, direction="out", channel="telegram", body_enc=encrypt(user.id, reply)))
        send(chat_id, reply)


def download(file_id: str, msg: dict) -> tuple[bytes, str]:
    s = get_settings()
    info = _api("getFile", file_id=file_id) or {}
    path = info.get("file_path")
    if not path:
        raise httpx.HTTPError("no file path")
    with httpx.Client(timeout=60, transport=_transport) as http:
        r = http.get(f"https://api.telegram.org/file/bot{s.telegram_bot_token}/{path}")
    r.raise_for_status()
    if msg.get("voice"):
        mime = msg["voice"].get("mime_type") or "audio/ogg"
    elif msg.get("audio"):
        mime = msg["audio"].get("mime_type") or "audio/mpeg"
    elif msg.get("photo"):
        mime = "image/jpeg"
    else:
        mime = (msg.get("document") or {}).get("mime_type") or "application/octet-stream"
    return r.content, mime


def register_webhook() -> None:
    """Point the bot at this server (called at startup when a bot token is set)."""
    s = get_settings()
    if not enabled() or not s.telegram_webhook_secret or not s.base_url.startswith("https://"):
        return
    _api("setWebhook", url=s.base_url.rstrip("/") + "/webhooks/telegram", secret_token=s.telegram_webhook_secret,
         allowed_updates=["message", "callback_query"], drop_pending_updates=False)
