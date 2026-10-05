"""Skills: reusable procedures. Built-in ones ship with the product; users teach their own
("save this as a skill"), which is how the assistant builds its own tools."""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Skill, User

BUILTIN: dict[str, dict] = {
    "inbox-triage": {
        "description": "Sort recent email into reply-now, waiting, FYI and unsubscribe, with drafts for reply-now",
        "instructions": "Search email from the last 2 days (newer_than:2d -category:promotions). Group messages into "
        "Reply now / Waiting on someone / FYI / Unsubscribe candidates. For each Reply-now item, propose_email a short "
        "reply in the user's voice. Finish with a 5-line summary.",
    },
    "meeting-prep": {
        "description": "Brief for the next meeting: who, history, open loops, what to ask",
        "instructions": "List calendar for today and tomorrow, pick the next meeting with attendees. For each attendee, "
        "lookup_person and search_email for recent threads. Return: purpose, attendee notes, open loops with them, "
        "3 suggested questions, and one thing to bring.",
    },
    "follow-up-chaser": {
        "description": "Find everything people owe the user and nudge politely",
        "instructions": "list_open_loops, take items owed_to_user older than 3 days, and propose_email a polite nudge "
        "for each (max 5), replying in the original thread when known.",
    },
    "subscription-audit": {
        "description": "Find recurring charges in email and suggest what to cancel",
        "instructions": "Call list_subscriptions. If few are known, search_email for 'receipt OR invoice OR renewal "
        "OR subscription newer_than:120d' and note recurring merchants. Present a table of merchant, amount, cadence, "
        "and a keep/cancel suggestion with the yearly saving. Offer to cancel via a web task (needs approval).",
    },
    "price-watch": {
        "description": "Watch a product page and alert when the price drops below a target",
        "instructions": "Ask for the product URL and target price if missing. Create a standing task with schedule "
        "'every 12h' whose instruction is: read_url the page, find the current price, and if it is at or below the "
        "target reply with the price and link; otherwise reply exactly NOTHING_NEW.",
    },
    "trip-planner": {
        "description": "Plan a trip: options, calendar holds, and a checklist",
        "instructions": "Confirm destination, dates, budget and preferences from memory. web_search for options "
        "(flights/trains, stays), shortlist 3 with prices and links, propose_event holds for travel times, and give a "
        "packing and documents checklist. Bookings go through propose_errand or purchase handoff.",
    },
    "weekly-review": {
        "description": "Sunday review: wins, slipped promises, goals progress, next week's plan",
        "instructions": "Review list_goals, list_open_loops and next week's calendar. Write: 3 wins, what slipped, "
        "progress per goal, the top 3 priorities for next week, and propose calendar focus blocks for them.",
    },
    "invoice-chaser": {
        "description": "Small business: chase unpaid invoices politely, escalating tone by age",
        "instructions": "search_email for 'invoice OR payment due OR outstanding newer_than:90d'. For invoices the "
        "user sent that have no payment confirmation later in the thread, propose_email a reminder: friendly under "
        "15 days, firm at 15-30, final notice over 30. Never invent amounts.",
    },
    "lead-reply": {
        "description": "Small business: reply fast to new customer enquiries and book a call",
        "instructions": "search_email for enquiries in the last 3 days (quote, pricing, interested, enquiry). For each "
        "unanswered one, find_free_slots for a 20-minute call and propose_email a reply that answers what is known, "
        "asks one qualifying question, and offers two slots.",
    },
    "review-responder": {
        "description": "Small business: draft replies to customer reviews and feedback emails",
        "instructions": "search_email for review notifications and feedback in the last 7 days. Draft a warm, specific "
        "reply for each; for negative ones, apologise, offer a fix and a direct contact. Propose them for approval.",
    },
    "daily-numbers": {
        "description": "Small business: pull today's orders, payments and issues from email into one summary",
        "instructions": "search_email newer_than:1d for orders, payments received, refunds and complaints. Summarise "
        "counts and totals where stated, list anything needing action, and add open loops for follow-ups.",
    },
}

_NAME = re.compile(r"[^a-z0-9-]")


def slug(name: str) -> str:
    return _NAME.sub("-", name.strip().lower().replace(" ", "-"))[:60].strip("-") or "skill"


def all_skills(session: Session, user: User) -> list[dict]:
    out = [{"name": k, "description": v["description"], "builtin": True} for k, v in BUILTIN.items()]
    for s in session.scalars(select(Skill).where(Skill.user_id == user.id).order_by(Skill.name)).all():
        out.append({"name": s.name, "description": s.description, "builtin": False, "id": s.id})
    return out


def get(session: Session, user: User, name: str) -> dict | None:
    n = slug(name)
    s = session.scalar(select(Skill).where(Skill.user_id == user.id, Skill.name == n))
    if s:
        s.uses += 1
        return {"name": s.name, "description": s.description, "instructions": s.instructions}
    if n in BUILTIN:
        return {"name": n, **BUILTIN[n]}
    return None


def create(session: Session, user: User, name: str, description: str, instructions: str) -> Skill:
    n = slug(name)
    if n in BUILTIN:
        n = f"my-{n}"
    s = session.scalar(select(Skill).where(Skill.user_id == user.id, Skill.name == n))
    if s is None:
        s = Skill(user_id=user.id, name=n, description=description[:255], instructions=instructions[:4000])
        session.add(s)
    else:
        s.description, s.instructions = description[:255], instructions[:4000]
    session.flush()
    return s


def prompt_block(session: Session, user: User) -> str:
    return "\n".join(f"- {s['name']}: {s['description']}" for s in all_skills(session, user))
