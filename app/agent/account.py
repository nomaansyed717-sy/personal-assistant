"""User-controlled data operations: what did you do, what do you know, forget, delete everything."""
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.context.people import find_person
from app.db import utcnow
from app.integrations.google import revoke
from app.models import AuditLog, Commitment, Connection, Event, Preference, User
from app.util import aware, zone

LABELS = {
    "executed": "Did",
    "proposed": "Suggested",
    "scheduled": "Scheduled",
    "approved": "You approved",
    "rejected": "You skipped",
    "cancelled": "Cancelled",
    "failed": "Failed",
    "delegated": "You delegated",
    "remembered": "Saved",
    "sync_failed": "Sync problem",
    "blocked": "Sentinel blocked",
    "task_created": "New standing task",
    "task_ran": "Ran task",
    "task_cancelled": "Stopped task",
    "goal_added": "New goal",
    "skill_created": "New skill",
    "vault_added": "Saved login",
    "forgot": "Forgot",
}


def activity_log(session: Session, user: User, hours: int = 24) -> str:
    rows = session.scalars(
        select(AuditLog)
        .where(AuditLog.user_id == user.id, AuditLog.at >= utcnow() - timedelta(hours=hours))
        .order_by(AuditLog.at)
    ).all()
    rows = [r for r in rows if r.action in LABELS]
    if not rows:
        return "Nothing in the last 24 hours."
    tz = zone(user.timezone)
    lines = [f"{aware(r.at).astimezone(tz):%H:%M} {LABELS[r.action]}: {r.detail[:140]}" for r in rows[-25:]]
    return "Last 24 hours:\n" + "\n".join(lines)


def what_i_know(session: Session, user: User, about: str | None = None) -> str:
    if about:
        people = find_person(session, user.id, about)
        if not people:
            return f"I don't have anyone matching '{about}'."
        p = people[0]
        loops = session.scalars(select(Commitment).where(Commitment.person_id == p.id, Commitment.status == "open")).all()
        lines = [
            f"*{p.name or p.email}* <{p.email}>",
            f"Relationship: {p.relationship_note or 'not known'}" + (" (you marked them important)" if p.pinned else ""),
            f"You've written to them {p.messages_out}x, they've written {p.messages_in}x.",
        ]
        lines += [f"• {'You owe' if c.direction == 'user_owes' else 'They owe'}: {c.description}" for c in loops]
        lines.append(f"Reply *forget {p.email}* to delete all of this.")
        return "\n".join(lines)
    prefs = session.scalars(select(Preference).where(Preference.user_id == user.id)).all()
    n_open = len(session.scalars(select(Commitment.id).where(Commitment.user_id == user.id, Commitment.status == "open")).all())
    conn = session.scalar(select(Connection).where(Connection.user_id == user.id))
    lines = [
        f"Name: {user.name or 'not set'} | Time zone: {user.timezone} | Daily brief: {user.brief_hour:02d}:00",
        f"Connected: {conn.account_email if conn else 'nothing yet'}",
        f"Open loops I'm tracking: {n_open}",
    ]
    if prefs:
        lines.append("Your preferences and rules:")
        lines += [f"• {p.text}" for p in prefs]
    lines.append("Ask 'what do you know about <name>' for a person, or 'delete everything' to wipe it all.")
    return "\n".join(lines)


def forget(session: Session, user: User, target: str) -> str:
    target = target.strip()
    from app.context import memory as mem

    n_mem = mem.forget(session, user, target)
    people = find_person(session, user.id, target)
    if people:
        p = people[0]
        session.execute(delete(Commitment).where(Commitment.person_id == p.id))
        label = p.email
        session.delete(p)
        audit(session, user.id, "forgot", "a person", actor="user")
        return f"Forgotten: {label} and everything I tracked about them."
    prefs = session.scalars(select(Preference).where(Preference.user_id == user.id)).all()
    hit = [p for p in prefs if target.lower() in p.text.lower()]
    if hit:
        for p in hit:
            session.delete(p)
        audit(session, user.id, "forgot", "a preference", actor="user")
        return f"Forgotten {len(hit)} saved preference(s)" + (f" and {n_mem} memories." if n_mem else ".")
    if n_mem:
        audit(session, user.id, "forgot", f"{n_mem} memories", actor="user")
        return f"Forgotten {n_mem} memor{'y' if n_mem == 1 else 'ies'}."
    return f"I couldn't find anything matching '{target}'."


def planned(session: Session, user: User) -> str:
    """What the assistant is about to do: proposals waiting, sends in the undo window, and standing tasks."""
    from app.models import Action, StandingTask

    tz = zone(user.timezone)
    waiting = session.scalars(select(Action).where(Action.user_id == user.id, Action.status == "proposed")
                              .order_by(Action.number)).all()
    sched = session.scalars(select(Action).where(Action.user_id == user.id, Action.status == "scheduled")).all()
    tasks = session.scalars(select(StandingTask).where(StandingTask.user_id == user.id, StandingTask.status == "active")
                            .order_by(StandingTask.next_run_at)).all()
    lines = []
    if sched:
        lines.append("*Running now or about to send*")
        lines += [f"• {a.preview.splitlines()[0][:120]}" for a in sched]
    if waiting:
        lines.append("*Waiting for your yes*")
        lines += [f"• #{a.number} {a.preview.splitlines()[0][:120]}" for a in waiting]
    if tasks:
        lines.append("*Standing tasks*")
        lines += [f"• {t.title}, next {aware(t.next_run_at).astimezone(tz):%a %H:%M} ({t.schedule})"
                  for t in tasks if t.next_run_at]
    if not lines:
        return "Nothing planned right now. Ask me to keep an eye on something and I'll set up a standing task."
    return "\n".join(lines) + "\n\nFull history: say *what did you do today*."


def delete_everything(session: Session, user: User) -> None:
    for conn in session.scalars(select(Connection).where(Connection.user_id == user.id)).all():
        revoke(conn)
    session.flush()
    session.delete(user)  # cascades to every table


def purge_raw(session: Session, retention_days: int) -> int:
    """Drop raw email/calendar text past the retention window; structured facts stay."""
    cutoff = utcnow() - timedelta(days=retention_days)
    rows = session.scalars(select(Event).where(Event.occurred_at < cutoff, Event.purged.is_(False))).all()
    for e in rows:
        e.body_enc = None
        e.purged = True
    return len(rows)
