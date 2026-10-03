"""People graph: who the user deals with and how much they matter."""
import math
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Action, Person
from app.util import aware

AUTOMATED = ("noreply", "no-reply", "donotreply", "do-not-reply", "notifications", "mailer-daemon", "bounce")


def is_automated(email: str | None) -> bool:
    if not email:
        return True
    local = email.split("@")[0].lower()
    return any(tag in local for tag in AUTOMATED)


def upsert_person(session: Session, user_id: int, email: str | None, name: str | None = None) -> Person | None:
    if not email or is_automated(email):
        return None
    email = email.lower().strip()
    person = session.scalar(select(Person).where(Person.user_id == user_id, Person.email == email))
    if person is None:
        person = Person(user_id=user_id, email=email, name=name)
        session.add(person)
        session.flush()
    elif name and not person.name:
        person.name = name
    return person


def touch(person: Person, when: datetime, outgoing: bool) -> None:
    if outgoing:
        person.messages_out += 1
    else:
        person.messages_in += 1
    if person.last_contact_at is None or aware(when) > aware(person.last_contact_at):
        person.last_contact_at = when
    person.importance = importance(person)


def importance(person: Person, approval_rate: float | None = None) -> float:
    """0..1. Two-way conversation matters most; people the user writes to are weighted above inbound-only senders.
    Approval history nudges it: a user who keeps acting on someone's items cares about them."""
    score = 0.1 + 0.18 * math.log1p(person.messages_out) + 0.06 * math.log1p(person.messages_in)
    if person.messages_out and person.messages_in:
        score += 0.1
    if approval_rate is not None:
        score += 0.2 * (approval_rate - 0.5)
    if person.pinned:
        score += 0.4
    return round(max(0.0, min(1.0, score)), 3)


def approval_rate(session: Session, person_id: int) -> float | None:
    rows = session.execute(
        select(Action.status, func.count())
        .where(Action.person_id == person_id, Action.status.in_(["executed", "scheduled", "rejected", "expired"]))
        .group_by(Action.status)
    ).all()
    counts = dict(rows)
    yes = counts.get("executed", 0) + counts.get("scheduled", 0)
    total = yes + counts.get("rejected", 0) + counts.get("expired", 0)
    return yes / total if total >= 3 else None


def refresh_importance(session: Session, person: Person) -> None:
    person.importance = importance(person, approval_rate(session, person.id))


def find_person(session: Session, user_id: int, query: str) -> list[Person]:
    q = f"%{query.lower().strip()}%"
    return session.scalars(
        select(Person)
        .where(Person.user_id == user_id, (func.lower(Person.name).like(q)) | (func.lower(Person.email).like(q)))
        .order_by(Person.importance.desc())
        .limit(5)
    ).all()
