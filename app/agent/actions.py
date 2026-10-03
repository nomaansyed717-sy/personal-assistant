"""Permission tiers, approvals, the undo window and execution.

Tier 0  read                         always allowed
Tier 1  reversible, private          acts, reports later (reminders, notes)
Tier 2  outbound to known contacts   asks; can be delegated per action kind
Tier 3  new contacts / voice calls   always shows the full text and asks
Tier 4  money, irreversible          always asks; never enters card numbers or passwords

The assistant never raises its own autonomy. Only the user's explicit
"always do X" creates a Delegation, and a Delegation never covers tier 3+.
"""
import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import get_settings
from app.context.people import refresh_importance
from app.db import utcnow
from app.execution import ExecutionError, NotAvailable, get_executor
from app.models import Action, Commitment, Delegation, Person, User
from app.util import aware

log = logging.getLogger(__name__)

KIND_TIERS = {
    "note": 1,
    "send_email": 2,
    "create_event": 2,
    "browser_task": 3,
    "phone_call": 3,
    "desktop_task": 3,
    "phone_task": 3,
    "payment": 4,
}
MAX_DELEGABLE_TIER = 2
PROPOSAL_TTL = timedelta(days=3)


LABELS = {
    "note": "reminder",
    "send_email": "email",
    "create_event": "calendar event",
    "browser_task": "web task",
    "phone_call": "phone call",
    "desktop_task": "desktop task",
    "phone_task": "phone task",
    "payment": "payment",
}


def _label(kind: str) -> str:
    return LABELS.get(kind, kind.replace("_", " "))


def _first_line(text: str) -> str:
    return text.splitlines()[0][:160] if text else ""


def is_known_contact(session: Session, user_id: int, email: str) -> bool:
    """Someone the user has written to before."""
    p = session.scalar(select(Person).where(Person.user_id == user_id, Person.email == email.lower()))
    return bool(p and p.messages_out > 0)


def tier_for(session: Session, user: User, kind: str, payload: dict) -> int:
    tier = KIND_TIERS.get(kind, 3)
    recipients = list(payload.get("to") or []) + list(payload.get("cc") or []) + list(payload.get("attendees") or [])
    if tier == 2 and any(not is_known_contact(session, user.id, r) for r in recipients):
        tier = 3
    return tier


def _next_number(session: Session, user_id: int) -> int:
    current = session.scalar(
        select(func.max(Action.number)).where(Action.user_id == user_id, Action.status == "proposed")
    )
    return (current or 0) + 1


def propose(
    session: Session,
    user: User,
    kind: str,
    payload: dict,
    preview: str,
    origin: str = "chat",
    commitment_id: int | None = None,
    person_id: int | None = None,
) -> Action:
    """Create an action. Delegated low-tier actions are scheduled behind the undo window;
    everything else waits for the user's yes."""
    tier = tier_for(session, user, kind, payload)
    action = Action(
        user_id=user.id,
        kind=kind,
        tier=tier,
        payload=payload,
        preview=preview,
        origin=origin,
        commitment_id=commitment_id,
        person_id=person_id,
    )
    delegation = session.scalar(select(Delegation).where(Delegation.user_id == user.id, Delegation.action_kind == kind))
    if delegation and tier <= min(delegation.max_tier, MAX_DELEGABLE_TIER):
        action.status = "scheduled"
        action.execute_after = utcnow() + timedelta(seconds=get_settings().undo_window_seconds)
        audit(session, user.id, "scheduled", f"{_label(kind)} (delegated): {_first_line(preview)}")
    else:
        action.status = "proposed"
        action.number = _next_number(session, user.id)
        audit(session, user.id, "proposed", f"#{action.number} {_label(kind)}: {_first_line(preview)}")
    session.add(action)
    session.flush()
    return action


def open_proposals(session: Session, user_id: int) -> list[Action]:
    return session.scalars(
        select(Action).where(Action.user_id == user_id, Action.status == "proposed").order_by(Action.number)
    ).all()


def by_number(session: Session, user_id: int, number: int) -> Action | None:
    return session.scalar(
        select(Action).where(Action.user_id == user_id, Action.status == "proposed", Action.number == number)
    )


def approve(session: Session, user: User, action: Action) -> str:
    """The user said yes: run it now (no undo delay for explicit approvals)."""
    audit(session, user.id, "approved", f"#{action.number} {_label(action.kind)}", actor="user")
    return execute(session, user, action)


def reject(session: Session, user: User, action: Action) -> None:
    action.status = "rejected"
    audit(session, user.id, "rejected", f"#{action.number} {_label(action.kind)}", actor="user")
    if action.commitment_id:
        c = session.get(Commitment, action.commitment_id)
        if c:
            c.times_surfaced += 1  # lowers its rank
    _learn(session, action)


def execute(session: Session, user: User, action: Action) -> str:
    try:
        result = get_executor(action.kind)(session, user, action)
    except NotAvailable as exc:
        action.status = "failed"
        action.result = str(exc)
        audit(session, user.id, "not_available", f"{action.kind}: {exc}")
        return f"I can't do that yet ({action.kind.replace('_', ' ')} isn't switched on). I've kept a note of it."
    except ExecutionError as exc:
        action.status = "failed"
        action.result = str(exc)[:500]
        audit(session, user.id, "failed", f"{action.kind}: {exc}")
        log.warning("action %s failed: %s", action.id, exc)
        return f"That didn't go through: {str(exc)[:160]}"
    action.status = "executed"
    action.executed_at = utcnow()
    action.result = result
    audit(session, user.id, "executed", result)
    if action.commitment_id:
        c = session.get(Commitment, action.commitment_id)
        if c and (c.direction == "user_owes" or action.kind == "note"):
            c.status = "done"
        elif c:
            c.last_surfaced_at = utcnow()  # we nudged them; keep it open until they deliver
    _learn(session, action)
    return result


def _learn(session: Session, action: Action) -> None:
    if action.person_id:
        person = session.get(Person, action.person_id)
        if person:
            refresh_importance(session, person)


def cancel_scheduled(session: Session, user: User) -> int:
    """STOP during the undo window."""
    rows = session.scalars(
        select(Action).where(Action.user_id == user.id, Action.status == "scheduled", Action.execute_after > utcnow())
    ).all()
    for a in rows:
        a.status = "cancelled"
        audit(session, user.id, "cancelled", f"{_label(a.kind)}: {_first_line(a.preview)}", actor="user")
    return len(rows)


def run_due(session: Session) -> int:
    """Worker: execute scheduled actions whose undo window has passed, expire stale proposals."""
    now = utcnow()
    due = session.scalars(select(Action).where(Action.status == "scheduled", Action.execute_after <= now)).all()
    for a in due:
        user = session.get(User, a.user_id)
        if user and not user.paused:
            execute(session, user, a)
    stale = session.scalars(select(Action).where(Action.status == "proposed", Action.created_at < now - PROPOSAL_TTL)).all()
    for a in stale:
        a.status = "expired"
        a.number = None
    return len(due)


def delegate(session: Session, user: User, kind: str) -> str:
    tier = KIND_TIERS.get(kind, 3)
    if tier > MAX_DELEGABLE_TIER:
        return "That kind of action always needs your yes, so I can't take it on automatically."
    d = session.scalar(select(Delegation).where(Delegation.user_id == user.id, Delegation.action_kind == kind))
    if d is None:
        session.add(Delegation(user_id=user.id, action_kind=kind, max_tier=MAX_DELEGABLE_TIER))
    audit(session, user.id, "delegated", kind, actor="user")
    return (
        f"Done. I'll handle {kind.replace('_', ' ')}s to people you've written to before on my own, "
        f"with a {get_settings().undo_window_seconds}-second window to reply STOP. New contacts still need your yes."
    )


def revoke_delegation(session: Session, user: User, kind: str | None = None) -> int:
    q = select(Delegation).where(Delegation.user_id == user.id)
    if kind:
        q = q.where(Delegation.action_kind == kind)
    rows = session.scalars(q).all()
    for d in rows:
        session.delete(d)
    audit(session, user.id, "delegation_revoked", kind or "all", actor="user")
    return len(rows)


def format_proposals(actions: list[Action], tz_name: str) -> str:
    lines = []
    for a in actions:
        flag = " (new contact, please check)" if a.tier >= 3 else ""
        lines.append(f"*{a.number}.*{flag} {a.preview}")
    return "\n\n".join(lines)


def proposal_age_ok(a: Action) -> bool:
    return utcnow() - aware(a.created_at) < PROPOSAL_TTL
