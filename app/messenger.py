"""Outbound messaging: splitting, persistence, and the WhatsApp 24-hour window."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels import get_channel
from app.config import get_settings
from app.crypto import decrypt, encrypt
from app.db import utcnow
from app.models import Message, User
from app.util import aware

WINDOW = timedelta(hours=23, minutes=30)  # a little under WhatsApp's 24h, to be safe


def split_message(text: str, limit: int) -> list[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for para in text.split("\n"):
        candidate = f"{current}\n{para}" if current else para
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(para) > limit:
            parts.append(para[:limit])
            para = para[limit:]
        current = para
    if current:
        parts.append(current)
    return parts


def window_open(user: User) -> bool:
    last = aware(user.last_inbound_at)
    return last is not None and utcnow() - last < WINDOW


def send(session: Session, user: User, text: str) -> None:
    """Send now if the session window is open; otherwise queue it and ping with the reopen template."""
    channel = get_channel()
    if channel.has_session_window and not window_open(user):
        _queue(session, user, text)
        return
    for part in split_message(text, channel.max_len):
        ext_id = channel.send_text(user.phone, part)
        session.add(
            Message(user_id=user.id, direction="out", channel=channel.name, body_enc=encrypt(user.id, part), external_id=ext_id)
        )


def _queue(session: Session, user: User, text: str) -> None:
    already_queued = session.scalar(
        select(Message.id).where(Message.user_id == user.id, Message.direction == "queued").limit(1)
    )
    session.add(Message(user_id=user.id, direction="queued", channel=get_channel().name, body_enc=encrypt(user.id, text)))
    if not already_queued:
        s = get_settings()
        name = (user.name or "").split(" ")[0] or "there"
        get_channel().send_template(user.phone, s.whatsapp_reopen_template, [name])


def flush_queue(session: Session, user: User) -> None:
    """Called after an inbound message reopens the window."""
    queued = session.scalars(
        select(Message).where(Message.user_id == user.id, Message.direction == "queued").order_by(Message.at)
    ).all()
    for msg in queued:
        text = decrypt(user.id, msg.body_enc)
        session.delete(msg)
        if text:
            send(session, user, text)


def record_inbound(session: Session, user: User, text: str, external_id: str | None, channel: str) -> bool:
    """Store an inbound message. Returns False when it is a duplicate webhook delivery."""
    if external_id and session.scalar(select(Message.id).where(Message.external_id == external_id)):
        return False
    session.add(
        Message(user_id=user.id, direction="in", channel=channel, body_enc=encrypt(user.id, text), external_id=external_id)
    )
    user.last_inbound_at = utcnow()
    return True


def recent_history(session: Session, user: User, limit: int = 12) -> list[dict]:
    rows = session.scalars(
        select(Message)
        .where(Message.user_id == user.id, Message.direction.in_(["in", "out"]))
        .order_by(Message.at.desc(), Message.id.desc())
        .limit(limit)
    ).all()
    out = []
    for m in reversed(rows):
        out.append({"role": "user" if m.direction == "in" else "assistant", "text": decrypt(user.id, m.body_enc) or ""})
    return out
