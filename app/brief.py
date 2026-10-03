"""The daily brief: today's calendar plus the 3-5 open loops that matter most, each with a ready action."""
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import actions
from app.agent.drafts import draft_for
from app.config import get_settings
from app.context.rank import top_open
from app.db import utcnow
from app.llm import LLM
from app.models import Action, Event, User
from app.util import aware, local_now, zone

HOW_TO_REPLY = "Reply with numbers to go ahead (e.g. *1, 3* or *all*), *edit 2: make it shorter*, or *skip 2*."


def todays_events(session: Session, user: User) -> list[Event]:
    tz = zone(user.timezone)
    today = local_now(user.timezone).date()
    start = datetime.combine(today, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return session.scalars(
        select(Event)
        .where(Event.user_id == user.id, Event.source == "calendar", Event.occurred_at >= start, Event.occurred_at < end)
        .order_by(Event.occurred_at)
    ).all()


def compose(session: Session, user: User, llm: LLM, greeting: str | None = None, origin: str = "brief") -> str:
    tz = user.timezone
    first = (user.name or "").split(" ")[0]
    hour = local_now(tz).hour
    part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    lines = [greeting or f"Good {part}{', ' + first if first else ''}."]

    events = todays_events(session, user)
    if events:
        lines.append("")
        lines.append(f"*Today* ({len(events)} on the calendar)")
        for e in events[:6]:
            if (e.meta or {}).get("all_day"):
                when = "All day"
            else:
                when = aware(e.occurred_at).astimezone(zone(tz)).strftime("%H:%M")
            lines.append(f"• {when} {e.subject}")

    # Items already proposed and still waiting stay as they are; we don't re-draft them.
    waiting = actions.open_proposals(session, user.id)
    waiting_commitments = {a.commitment_id for a in waiting if a.commitment_id}
    loops = [c for c in top_open(session, user.id, get_settings().brief_max_items) if c.id not in waiting_commitments]
    new_actions: list[Action] = []
    for c in loops:
        new_actions.append(draft_for(session, user, c, llm, origin=origin))
        c.times_surfaced += 1
        c.last_surfaced_at = utcnow()

    proposals = actions.open_proposals(session, user.id)
    if proposals:
        lines.append("")
        lines.append("*Open loops*")
        lines.append(actions.format_proposals(proposals, tz))
        lines.append("")
        lines.append(HOW_TO_REPLY)
    elif not events:
        lines.append("Nothing open that needs you today. Enjoy it.")

    scheduled = [a for a in new_actions if a.status == "scheduled"]
    if scheduled:
        lines.append("")
        lines.append(f"I'm also sending {len(scheduled)} follow-up(s) you've delegated in a minute. Reply STOP to hold them.")
    return "\n".join(lines)


def due_for_brief(user: User) -> bool:
    now = local_now(user.timezone)
    return (
        user.onboarding_state == "active"
        and not user.paused
        and now.hour == user.brief_hour
        and user.last_brief_on != now.date()
    )


def mark_sent(user: User) -> None:
    user.last_brief_on = local_now(user.timezone).date()
