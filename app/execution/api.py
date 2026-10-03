"""Rung 1 of the ladder: official APIs."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.execution import ExecutionError, register
from app.integrations.google import GoogleError
from app.integrations.sync import google_client
from app.models import Action, User


def _client(session: Session, user: User):
    client = google_client(session, user)
    if client is None:
        raise ExecutionError("Google isn't connected")
    return client


@register("note")
def note(session: Session, user: User, action: Action) -> str:
    """A reminder the user marked as handled; nothing leaves the system."""
    return "Marked as handled"


@register("send_email")
def send_email(session: Session, user: User, action: Action) -> str:
    p = action.payload
    try:
        _client(session, user).send_email(
            to=p["to"],
            cc=p.get("cc") or None,
            subject=p.get("subject", ""),
            body=p["body"],
            thread_id=p.get("thread_id"),
            in_reply_to=p.get("in_reply_to"),
        )
    except GoogleError as exc:
        raise ExecutionError(str(exc)) from exc
    return f"Sent to {', '.join(p['to'])}"


@register("create_event")
def create_event(session: Session, user: User, action: Action) -> str:
    p = action.payload
    try:
        _client(session, user).create_event(
            title=p["title"],
            start=datetime.fromisoformat(p["start"]),
            end=datetime.fromisoformat(p["end"]),
            attendees=p.get("attendees") or None,
            description=p.get("description", ""),
        )
    except GoogleError as exc:
        raise ExecutionError(str(exc)) from exc
    who = f" with {', '.join(p['attendees'])}" if p.get("attendees") else ""
    return f"Added '{p['title']}'{who}"
