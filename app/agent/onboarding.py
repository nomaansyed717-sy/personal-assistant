"""First contact to first value in under ten minutes, entirely in chat."""
import logging

from sqlalchemy.orm import Session

from app import brief
from app.audit import audit
from app.config import get_settings
from app.context.extract import process_pending
from app.context.voice import build_voice_profile
from app.integrations import google
from app.integrations.sync import sync_user
from app.llm import LLM
from app.messenger import send
from app.models import Consent, User

log = logging.getLogger(__name__)

YES = {"yes", "y", "agree", "i agree", "ok", "okay", "sure", "haan", "si", "sí", "oui", "ja", "да", "نعم", "हाँ", "हां"}


def welcome(user: User) -> str:
    s = get_settings()
    first = (user.name or "").split(" ")[0]
    return (
        f"Hi{' ' + first if first else ''}, I'm {s.app_name}, your chief of staff on WhatsApp.\n\n"
        "I read your email and calendar, keep track of what you've promised and what you're owed, "
        "and each morning I text you the few things that need you, with replies ready to send.\n\n"
        "How I handle your data: everything is encrypted, I never send anything to someone new without your yes, "
        "I don't read your WhatsApp chats, and you can say *delete everything* at any time.\n"
        f"Terms and privacy: {s.base_url.rstrip('/')}/privacy\n\n"
        f"I've set your time zone to *{user.timezone}* from your number (say *timezone Europe/London* to change it).\n\n"
        "Reply *YES* to agree and connect your Google account."
    )


def handle(session: Session, user: User, text: str) -> str | None:
    """Returns the reply while onboarding, or None once the user is active."""
    state = user.onboarding_state
    t = text.strip().lower().rstrip(".!")

    if state == "new":
        user.onboarding_state = "awaiting_consent"
        return welcome(user)

    if state == "awaiting_consent":
        if t in YES:
            session.add(Consent(user_id=user.id, scope="terms", granted=True))
            audit(session, user.id, "consent", "terms", actor="user")
            user.onboarding_state = "awaiting_connect"
            return connect_message(session, user)
        return "No problem. Whenever you're ready, reply *YES* to agree to the terms and get started."

    if state == "awaiting_connect":
        return "I'm still waiting for Google access. Here's a fresh link:\n" + google.start_url(session, user.id)

    if state == "syncing":
        return "I'm reading through your last few weeks of email now. I'll text you what I find in a few minutes."

    return None


def connect_message(session: Session, user: User) -> str:
    return (
        "Great. Tap this link to connect Gmail and Google Calendar (read your mail and calendar, "
        "send only what you approve):\n"
        f"{google.start_url(session, user.id)}\n\n"
        "Outlook and other providers are coming."
    )


def after_connect(session: Session, user: User, llm: LLM) -> None:
    """Runs in the background right after Google OAuth: first sync, first insights, first brief."""
    session.add(Consent(user_id=user.id, scope="gmail", granted=True))
    session.add(Consent(user_id=user.id, scope="calendar", granted=True))
    user.onboarding_state = "syncing"
    session.flush()
    send(session, user, "Connected. Give me a few minutes to read the last few weeks.")
    stats = sync_user(session, user)
    if "error" in stats:
        send(session, user, "I couldn't read your mail just now. I'll keep trying and let you know.")
        return
    process_pending(session, user, llm)
    try:
        build_voice_profile(session, user, llm)
    except Exception:  # noqa: BLE001 - the voice profile is a nice-to-have at this point
        log.exception("voice profile failed for user %s", user.id)
    user.onboarding_state = "active"
    intro = "Here's what looks open right now."
    message = brief.compose(session, user, llm, greeting=intro, origin="onboarding")
    send(session, user, message)
    send(
        session,
        user,
        "Three quick questions so I get your priorities right: who matters most to you right now, "
        "what are you working on this month, and is there anything I must never do? "
        f"I'll send your brief every day at {user.brief_hour:02d}:00 (say *brief at 7* to change it).",
    )
    brief.mark_sent(user)
