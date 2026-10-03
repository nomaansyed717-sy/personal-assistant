"""Decide which open loops matter most today."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Commitment
from app.util import aware


def score(c: Commitment, now: datetime | None = None) -> float:
    """Higher = more worth the user's attention today.

    Signals: who is involved, whether it touches an active project, how late it is,
    which way it runs, how sure we are, and how often we've already raised it."""
    now = now or utcnow()
    s = 0.0
    s += 2.0 * (c.person.importance if c.person else 0.25)
    if c.project and c.project.active:
        s += 0.6
    s += 0.6 if c.direction == "user_owes" else 0.3  # the user's own promises come first

    due = aware(c.due_at)
    if due:
        days = (due - now).total_seconds() / 86400
        if days < 0:
            s += min(1.5, 0.5 + 0.15 * -days)  # overdue, growing up to a cap
        elif days <= 1:
            s += 1.2
        elif days <= 3:
            s += 0.6
    else:
        age = (now - aware(c.made_at)).days
        if 2 <= age <= 14:
            s += 0.5  # the classic dropped thread: a few days old, no date, nobody chased it
        elif age > 30:
            s -= 0.8

    s *= 0.5 + 0.5 * c.confidence
    s -= 0.35 * min(c.times_surfaced, 4)  # don't nag about the same thing every morning
    return round(s, 3)


def top_open(session: Session, user_id: int, limit: int = 5, now: datetime | None = None) -> list[Commitment]:
    now = now or utcnow()
    items = session.scalars(
        select(Commitment).where(Commitment.user_id == user_id, Commitment.status.in_(["open", "snoozed"]))
    ).all()
    live = []
    for c in items:
        if c.status == "snoozed":
            if c.snoozed_until and aware(c.snoozed_until) > now:
                continue
            c.status = "open"
        live.append(c)
    live.sort(key=lambda c: score(c, now), reverse=True)
    return live[:limit]


def snooze(c: Commitment, days: int = 3) -> None:
    c.status = "snoozed"
    c.snoozed_until = utcnow() + timedelta(days=days)
