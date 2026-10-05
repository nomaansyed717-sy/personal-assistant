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
from app.config import get_settings
from app.context import memory
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
NAME_ME = re.compile(r"^(?:call yourself|your name is|i(?:'ll| will) call you|be called)\s+([\w .'-]{1,40})$", re.I)
REMEMBER_Q = re.compile(r"^what do you remember(?: about me)?\??$", re.I)
PLANNING = re.compile(r"^(?:what are you (?:planning|working on)|what'?s planned|plans|planned|what will you do)\??$", re.I)
APP_LINK = re.compile(r"^(?:app|web app|open app|login|log in|sign in|dashboard|app link)$", re.I)
UNDELEGATE = re.compile(r"^(?:stop auto(?:matic)?(?:ally)?(?: sending)?|ask me first(?: again)?|no more auto(?:matic)? (?:sending|follow[- ]?ups))$", re.I)


DELETED = "\x00deleted:"


def _numbers(s: str) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", s)]


def get_or_create_user(session: Session, msg: InboundMessage) -> User:
    user = session.scalar(select(User).where(User.phone == msg.phone))
    if user is None:
        user = User(phone=msg.phone, name=msg.profile_name, timezone=guess_timezone(msg.phone),
                    assistant_name=get_settings().app_name)
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
    text, attachments = msg.text, []
    if msg.media_id and user.onboarding_state == "active":
        from app.media import MediaError, prepare

        try:
            text, attachments = prepare(msg)
        except MediaError as exc:
            send(session, user, str(exc))
            return
        except Exception:  # noqa: BLE001
            log.exception("media download failed")
            send(session, user, "I couldn't open that file. Could you send it again?")
            return
    elif msg.kind == "unsupported" or not msg.text:
        send(session, user, "I can read text, photos, PDFs and voice notes. That one I can't open yet.")
        return
    reply = route(session, user, text, llm, attachments)
    if reply and reply.startswith(DELETED):
        goodbye(get_channel(), reply.removeprefix(DELETED))
    elif reply:
        send(session, user, reply)


def route(session: Session, user: User, text: str, llm: LLM, attachments: list[dict] | None = None) -> str | None:
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
    if m := NAME_ME.match(t):
        user.assistant_name = m.group(1).strip().title()[:60]
        audit(session, user.id, "renamed_assistant", user.assistant_name, actor="user")
        return f"Love it. I'm {user.assistant_name} from now on."
    if REMEMBER_Q.match(low):
        mems = memory.all_memories(session, user)
        if not mems:
            return "I haven't saved anything about you yet. Tell me what matters and I'll remember it."
        lines = [f"• {t}" for _, t in mems[:30]]
        return "Here's what I remember:\n" + "\n".join(lines) + "\n\nSay *forget <something>* to remove any of it."
    if PLANNING.match(low):
        return account.planned(session, user)
    if APP_LINK.match(low):
        return f"Open the web app here and sign in with your number: {get_settings().base_url.rstrip('/')}/app"
    if low in ("no ideas", "stop ideas", "ideas off"):
        user.ideas_enabled = False
        return "Okay, no more daily ideas. Say *ideas on* to bring them back."
    if low in ("ideas on", "send ideas"):
        user.ideas_enabled = True
        return "Done. I'll send a few ideas each evening when I have good ones."
    if low in ("add a login", "save a login", "save password", "vault"):
        return ("Never send passwords in chat. Add logins in your vault, where only the secure browser can use them "
                f"(I never see them): {get_settings().base_url.rstrip('/')}/app#vault")
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

    return agent.respond(session, user, t, llm, attachments)


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
