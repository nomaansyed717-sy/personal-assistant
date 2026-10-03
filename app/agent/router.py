"""Entry point for every inbound message.

Cheap, predictable commands (approvals, STOP, delete) are parsed deterministically.
Everything else goes to the agent. Autonomy changes (delegation) are only ever
made here, from the user's own words, never by the model.
"""
import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import brief
from app.agent import account, actions, agent, drafts, onboarding
from app.audit import audit
from app.channels import InboundMessage, get_channel
from app.context.rank import snooze
from app.llm import LLM
from app.messenger import flush_queue, record_inbound, send
from app.models import Commitment, User
from app.util import guess_timezone

log = logging.getLogger(__name__)

NUM_LIST = re.compile(r"^(?:send|yes|ok|okay|approve|go|do)?\s*((?:\d+\s*(?:,|and|&|\s)\s*)*\d+)\s*$", re.I)
ALL = re.compile(r"^(?:send |approve |do )?(?:all|all of them|everything)$", re.I)
SKIP = re.compile(r"^(?:skip|no|drop|reject|don'?t send)\s+((?:\d+\s*,?\s*)+)$", re.I)
EDIT = re.compile(r"^(?:edit|change)\s+(\d+)\s*[:\-]?\s*(.+)$", re.I | re.S)
SNOOZE = re.compile(r"^snooze\s+(\d+)(?:\s+(?:for\s+)?(\d+)\s*d(?:ays?)?)?$", re.I)
DONE = re.compile(r"^(?:done|handled)\s+(\d+)$", re.I)
FORGET = re.compile(r"^forget\s+(.+)$", re.I)
KNOW = re.compile(r"^what do you know(?: about (.+?))?\??$", re.I)
TZ = re.compile(r"^(?:timezone|time zone)\s+([A-Za-z_]+/[A-Za-z_/]+)$", re.I)
BRIEF_AT = re.compile(r"^brief at\s+(\d{1,2})(?::00)?\s*(am|pm)?$", re.I)
DELEGATE = re.compile(r"^(?:always|automatically)\s+(?:send|handle)\s+(?:my\s+)?(follow[- ]?ups?|emails?|replies|nudges)\b", re.I)
UNDELEGATE = re.compile(r"^(?:stop auto(?:matic)?(?:ally)?(?: sending)?|ask me first(?: again)?|no more auto(?:matic)? (?:sending|follow[- ]?ups))$", re.I)


DELETED = "\x00deleted:"


def _numbers(s: str) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", s)]


def get_or_create_user(session: Session, msg: InboundMessage) -> User:
    user = session.scalar(select(User).where(User.phone == msg.phone))
    if user is None:
        user = User(phone=msg.phone, name=msg.profile_name, timezone=guess_timezone(msg.phone))
        session.add(user)
        session.flush()
        audit(session, user.id, "signup", "", actor="user")
    elif msg.profile_name and not user.name:
        user.name = msg.profile_name
    return user


def handle_inbound(session: Session, msg: InboundMessage, llm: LLM, channel_name: str = "whatsapp") -> None:
    user = get_or_create_user(session, msg)
    if not record_inbound(session, user, msg.text, msg.external_id, channel_name):
        return  # duplicate delivery
    flush_queue(session, user)
    if msg.kind == "unsupported" or not msg.text:
        send(session, user, "I can only read text for now. Voice notes and images are coming.")
        return
    reply = route(session, user, msg.text, llm)
    if reply and reply.startswith(DELETED):
        goodbye(get_channel(), reply.removeprefix(DELETED))
    elif reply:
        send(session, user, reply)


def route(session: Session, user: User, text: str, llm: LLM) -> str | None:
    t = text.strip()
    low = t.lower().rstrip(".!")

    # Destructive confirmation comes first so nothing else can intercept it.
    if user.pending_confirmation == "delete_everything":
        user.pending_confirmation = None
        if t == "DELETE":
            phone = user.phone
            account.delete_everything(session, user)
            return DELETED + phone
        return "Okay, nothing was deleted."

    onboarding_reply = onboarding.handle(session, user, t)
    if onboarding_reply is not None:
        return onboarding_reply

    if low in ("stop", "hold", "wait", "cancel"):
        n = actions.cancel_scheduled(session, user)
        if n:
            return f"Held {n} message(s). Nothing went out."
        user.paused = True
        return "Paused. I won't message you first until you say *resume*."
    if low in ("resume", "start", "unpause"):
        user.paused = False
        return f"Back on. Your next brief comes at {user.brief_hour:02d}:00."

    if low == "delete everything":
        user.pending_confirmation = "delete_everything"
        return (
            "This deletes your account, every message, everything I've learned, and disconnects Google. "
            "It can't be undone. Reply *DELETE* (in capitals) to confirm."
        )
    if low in ("what did you do today", "what did you do", "log", "activity", "history"):
        return account.activity_log(session, user)
    if m := KNOW.match(low):
        return account.what_i_know(session, user, m.group(1))
    if m := FORGET.match(t):
        return account.forget(session, user, m.group(1))
    if low in ("brief", "brief now", "my brief", "what's open", "whats open", "open loops"):
        return brief.compose(session, user, llm, origin="chat")
    if m := TZ.match(t):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(m.group(1))
        except (ZoneInfoNotFoundError, ValueError):
            return "I don't recognise that time zone. Try something like *timezone Asia/Kolkata* or *timezone America/New_York*."
        user.timezone = m.group(1)
        return f"Time zone set to {user.timezone}."
    if m := BRIEF_AT.match(low):
        hour = int(m.group(1)) % 12 if m.group(2) else int(m.group(1))
        if m.group(2) == "pm":
            hour += 12
        if not 0 <= hour <= 23:
            return "Give me an hour between 0 and 23, like *brief at 7*."
        user.brief_hour = hour
        return f"Done. Your brief comes at {hour:02d}:00 {user.timezone} time."
    if DELEGATE.match(low):
        return actions.delegate(session, user, "send_email")
    if UNDELEGATE.match(low):
        actions.revoke_delegation(session, user)
        return "Okay. I'll ask before sending anything."

    proposals = actions.open_proposals(session, user.id)
    if proposals:
        handled = _approval_commands(session, user, t, low, proposals, llm)
        if handled is not None:
            return handled
    if m := DONE.match(low):
        return _close_by_number(session, user, int(m.group(1)), "done")
    if m := SNOOZE.match(low):
        return _close_by_number(session, user, int(m.group(1)), "snooze", int(m.group(2) or 3))

    return agent.respond(session, user, t, llm)


def _approval_commands(session, user, t, low, proposals, llm) -> str | None:
    if ALL.match(low):
        return _approve(session, user, [a.number for a in proposals])
    if m := NUM_LIST.match(low):
        return _approve(session, user, _numbers(m.group(1)))
    if m := SKIP.match(low):
        out = []
        for n in _numbers(m.group(1)):
            a = actions.by_number(session, user.id, n)
            if a:
                actions.reject(session, user, a)
                out.append(str(n))
        return f"Skipped {', '.join(out)}." if out else "I don't have those numbers open."
    if m := EDIT.match(t):
        a = actions.by_number(session, user.id, int(m.group(1)))
        if not a:
            return "I don't have that number open."
        if a.kind != "send_email":
            return "Only email drafts can be edited. Tell me what you'd like instead."
        drafts.revise(session, user, a, m.group(2), llm)
        return f"*{a.number}.* {a.preview}\n\nReply *{a.number}* to send."
    return None


def _approve(session: Session, user: User, numbers: list[int]) -> str:
    results = []
    for n in dict.fromkeys(numbers):  # de-duplicate, keep order
        a = actions.by_number(session, user.id, n)
        if a is None:
            results.append((n, "that number isn't open"))
            continue
        results.append((n, actions.approve(session, user, a)))
    if len(results) == 1:
        return f"{results[0][1]}."
    return "\n".join(f"{n}. {r}" for n, r in results)


def _close_by_number(session, user, number, how, days=3) -> str:
    a = actions.by_number(session, user.id, number)
    if not a or not a.commitment_id:
        return "I don't have that number open."
    c = session.get(Commitment, a.commitment_id)
    a.status = "cancelled"
    a.number = None
    if how == "done":
        c.status = "done"
        audit(session, user.id, "loop_done", c.description, actor="user")
        return "Marked done."
    snooze(c, days)
    audit(session, user.id, "loop_snoozed", c.description, actor="user")
    return f"Snoozed for {days} days."


def goodbye(channel, phone: str) -> None:
    channel.send_text(phone, "Everything is deleted and Google is disconnected. Thanks for trying me. Say hi any time to start fresh.")
