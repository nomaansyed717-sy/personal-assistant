"""Push notifications to the Android app (and iOS later) through Expo's push service.

Messages are already stored in the user's in-app inbox; a push only tells the phone there is
something new. Users can hide message text from the lock screen (push_previews = False).
Tokens Expo reports as DeviceNotRegistered are removed.
"""
import logging
from collections.abc import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import Device, User

log = logging.getLogger(__name__)
EXPO_URL = "https://exp.host/--/api/v2/push/send"
PREVIEW_CHARS = 180

# Swappable for tests: takes the list of Expo messages, returns Expo's per-message tickets.
Sender = Callable[[list[dict]], list[dict]]


def _expo_send(messages: list[dict]) -> list[dict]:
    s = get_settings()
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if s.expo_access_token:
        headers["Authorization"] = f"Bearer {s.expo_access_token}"
    r = httpx.post(EXPO_URL, json=messages, headers=headers, timeout=10)
    r.raise_for_status()
    return r.json().get("data", [])


_sender: Sender = _expo_send


def set_sender(sender: Sender | None) -> None:
    global _sender
    _sender = sender or _expo_send


def register(session: Session, user: User, token: str, platform: str) -> Device:
    dev = session.scalar(select(Device).where(Device.push_token == token))
    if dev:
        dev.user_id, dev.platform, dev.last_seen_at = user.id, platform, utcnow()  # a phone can change hands
    else:
        dev = Device(user_id=user.id, push_token=token, platform=platform)
        session.add(dev)
    return dev


def unregister(session: Session, user: User, token: str) -> bool:
    dev = session.scalar(select(Device).where(Device.push_token == token, Device.user_id == user.id))
    if dev:
        session.delete(dev)
        return True
    return False


def notify(session: Session, user: User, text: str, kind: str = "message") -> int:
    """Push to every registered device. Never raises: the message is already in the inbox."""
    devices = session.scalars(select(Device).where(Device.user_id == user.id)).all()
    if not devices or user.demo:
        return 0
    title = user.assistant_name or get_settings().app_name
    body = text.strip().replace("*", "")
    if len(body) > PREVIEW_CHARS:
        body = body[: PREVIEW_CHARS - 1].rstrip() + "…"
    if not user.push_previews:
        body = "You have a new message."
    messages = [{"to": d.push_token, "title": title, "body": body, "sound": "default", "priority": "high",
                 "channelId": "default", "data": {"kind": kind}} for d in devices]
    try:
        tickets = _sender(messages)
    except Exception:  # noqa: BLE001 - delivery is best effort
        log.exception("push failed for user %s", user.id)
        return 0
    sent = 0
    for dev, ticket in zip(devices, tickets, strict=False):
        if ticket.get("status") == "ok":
            sent += 1
        elif (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
            session.delete(dev)
    return sent
