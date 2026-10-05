"""Goals and proactive ideas: the assistant works toward the user's goals and suggests next steps."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.drafts import loop_line
from app.context import memory
from app.context.rank import top_open
from app.llm import LLM
from app.models import Goal, User
from app.util import local_now

log = logging.getLogger(__name__)
IDEAS_HOUR = 18  # local time, after the working day

SYSTEM = """You are a proactive chief of staff. Given a person's goals, what you know about them, their open
loops and their upcoming calendar, suggest up to 3 concrete next steps that move a goal forward or save them
time or money this week. Each idea must be specific and doable by the assistant with their approval
(draft an email, book a slot, set up a watch, research options) or by them in under 15 minutes.
No generic advice. If nothing is genuinely useful, return no ideas."""

SCHEMA = {
    "type": "object",
    "properties": {
        "ideas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "idea": {"type": "string", "description": "One or two sentences"},
                    "goal": {"type": ["string", "null"]},
                },
                "required": ["idea"],
            },
        }
    },
    "required": ["ideas"],
}


def active_goals(session: Session, user: User) -> list[Goal]:
    return session.scalars(
        select(Goal).where(Goal.user_id == user.id, Goal.status == "active").order_by(Goal.created_at)
    ).all()


def goals_block(session: Session, user: User) -> str:
    return "\n".join(
        f"- [goal {g.id}] {g.title}" + (f" (by {g.target_date})" if g.target_date else "")
        + (f" | progress: {g.progress_note}" if g.progress_note else "")
        for g in active_goals(session, user)
    ) or "- none set yet"


def due(user: User) -> bool:
    now = local_now(user.timezone)
    return (
        user.onboarding_state == "active" and user.ideas_enabled and not user.paused
        and now.hour == IDEAS_HOUR and user.last_ideas_on != now.date()
    )


def compose(session: Session, user: User, llm: LLM) -> str | None:
    from app.agent.tools import event_summary

    goals = goals_block(session, user)
    mems = memory.prompt_block(session, user)
    if goals.startswith("- none") and mems.startswith("- nothing"):
        return None
    loops = "\n".join(f"- {loop_line(c, user.timezone)}" for c in top_open(session, user.id, 8)) or "- none"
    content = (f"Goals:\n{goals}\n\nWhat you know about them:\n{mems}\n\nOpen loops:\n{loops}\n\n"
               f"Calendar, next days:\n{event_summary(session, user, days=5)}")
    try:
        result = llm.extract(SYSTEM, content, "suggest_ideas", SCHEMA, fast=False)
    except Exception:  # noqa: BLE001
        log.exception("ideas failed for user %s", user.id)
        return None
    ideas = [i for i in (result.get("ideas") or []) if i.get("idea")][:3]
    if not ideas:
        return None
    lines = ["*A few ideas for this week*"]
    for n, i in enumerate(ideas, 1):
        tag = f" _(goal: {i['goal']})_" if i.get("goal") else ""
        lines.append(f"{n}. {i['idea']}{tag}")
    lines.append("\nReply with what you'd like me to do, e.g. *do idea 2*. Say *no ideas* to turn these off.")
    return "\n".join(lines)


def mark_sent(user: User) -> None:
    user.last_ideas_on = local_now(user.timezone).date()
