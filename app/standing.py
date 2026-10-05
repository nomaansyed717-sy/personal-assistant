"""Standing tasks: the assistant keeps working after the user closes the chat.

Examples: "every morning check if my visa appointment slot opened", "watch this price",
"every Friday chase unpaid invoices". The worker runs each due task through the agent in
background mode and messages the user only when there is something worth saying.
"""
import logging
import re
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import utcnow
from app.models import StandingTask, User
from app.util import aware, zone

log = logging.getLogger(__name__)

NOTHING_NEW = "NOTHING_NEW"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DAILY = re.compile(r"^daily (\d{1,2}):(\d{2})$")
_WEEKLY = re.compile(r"^weekly (mon|tue|wed|thu|fri|sat|sun) (\d{1,2}):(\d{2})$")
_EVERY = re.compile(r"^every (\d{1,3})\s*(m|h|d)$")
_ONCE = re.compile(r"^once (\d{4}-\d{2}-\d{2}T\d{2}:\d{2})$")
MIN_INTERVAL = timedelta(minutes=30)
MAX_ACTIVE_TASKS = 25


class ScheduleError(ValueError):
    pass


def normalize(schedule: str) -> str:
    s = " ".join(schedule.strip().lower().split())
    if s.startswith("once "):
        s = "once " + s[5:].upper()
    if not (_DAILY.match(s) or _WEEKLY.match(s) or _EVERY.match(s) or _ONCE.match(s)):
        raise ScheduleError(
            "schedule must be one of: 'daily HH:MM', 'weekly mon HH:MM', 'every 6h' (m/h/d), 'once YYYY-MM-DDTHH:MM'"
        )
    m = _EVERY.match(s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[unit]: n}) < MIN_INTERVAL:
            raise ScheduleError("the shortest interval is every 30m")
    return s


def next_run(schedule: str, tz_name: str, after: datetime | None = None) -> datetime | None:
    """Next fire time (UTC) strictly after `after`. None for a one-off that has passed."""
    after = aware(after) or utcnow()
    tz = zone(tz_name)
    local = after.astimezone(tz)
    if m := _DAILY.match(schedule):
        t = time(int(m.group(1)), int(m.group(2)))
        cand = datetime.combine(local.date(), t, tzinfo=tz)
        if cand <= local:
            cand += timedelta(days=1)
        return cand.astimezone(after.tzinfo)
    if m := _WEEKLY.match(schedule):
        dow, t = DAYS.index(m.group(1)), time(int(m.group(2)), int(m.group(3)))
        cand = datetime.combine(local.date() + timedelta(days=(dow - local.weekday()) % 7), t, tzinfo=tz)
        if cand <= local:
            cand += timedelta(days=7)
        return cand.astimezone(after.tzinfo)
    if m := _EVERY.match(schedule):
        n, unit = int(m.group(1)), m.group(2)
        return after + timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[unit]: n})
    if m := _ONCE.match(schedule):
        cand = datetime.fromisoformat(m.group(1)).replace(tzinfo=tz)
        return cand.astimezone(after.tzinfo) if cand > local else None
    return None


def create(session: Session, user: User, title: str, instruction: str, schedule: str, goal_id: int | None = None) -> StandingTask:
    active = session.scalars(
        select(StandingTask.id).where(StandingTask.user_id == user.id, StandingTask.status == "active")
    ).all()
    if len(active) >= MAX_ACTIVE_TASKS:
        raise ScheduleError(f"you already have {MAX_ACTIVE_TASKS} active tasks; cancel one first")
    sched = normalize(schedule)
    first = next_run(sched, user.timezone)
    if first is None:
        raise ScheduleError("that time has already passed")
    t = StandingTask(user_id=user.id, title=title[:255], instruction=instruction[:4000], schedule=sched,
                     goal_id=goal_id, next_run_at=first)
    session.add(t)
    session.flush()
    audit(session, user.id, "task_created", f"{t.title} ({sched})", actor="user")
    return t


def describe(t: StandingTask, tz_name: str) -> str:
    nxt = aware(t.next_run_at).astimezone(zone(tz_name)).strftime("%a %d %b %H:%M") if t.next_run_at else "-"
    return f"[task {t.id}] {t.title} | {t.schedule} | next {nxt} | {t.status}"


def run_due(session: Session, runner, now: datetime | None = None, limit: int = 20) -> int:
    """Execute due tasks. `runner(session, user, task) -> str` does the work (the agent in background mode)."""
    from app.messenger import send

    now = now or utcnow()
    due = session.scalars(
        select(StandingTask)
        .where(StandingTask.status == "active", StandingTask.next_run_at <= now)
        .order_by(StandingTask.next_run_at)
        .limit(limit)
    ).all()
    for t in due:
        user = session.get(User, t.user_id)
        if user is None or user.paused:
            t.next_run_at = next_run(t.schedule, user.timezone if user else "UTC", now)
            continue
        try:
            result = (runner(session, user, t) or "").strip()
        except Exception as exc:  # noqa: BLE001
            log.exception("task %s failed", t.id)
            result = f"(error: {str(exc)[:200]})"
        t.runs += 1
        t.last_run_at = now
        t.last_result = result[:4000]
        t.next_run_at = None if t.schedule.startswith("once") else next_run(t.schedule, user.timezone, now)
        if t.next_run_at is None:
            t.status = "done"
        audit(session, user.id, "task_ran", f"{t.title}: {result[:160]}")
        if result and NOTHING_NEW not in result:
            send(session, user, f"*{t.title}*\n{result}")
    return len(due)
