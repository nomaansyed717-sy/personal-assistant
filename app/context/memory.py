"""Long-term memory: durable facts learned from conversations, visible and deletable by the user."""
import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import decrypt, encrypt
from app.llm import LLM
from app.models import Memory, User

log = logging.getLogger(__name__)
MAX_MEMORIES_IN_PROMPT = 40

SYSTEM = """You decide what is worth remembering long-term about a person from one message they sent
to their personal assistant. Save only durable facts that will help later: their priorities, projects,
people who matter and their roles, routines, preferences (food, travel, brands, times), constraints
("I don't take calls before 10"), and goals. Skip small talk, one-off requests, and anything already
in the known memories. Never save: health conditions, religion, politics, sexuality, ethnicity,
financial account details, passwords, government IDs or card numbers. Write each memory as one
short third-person sentence, e.g. "Prefers aisle seats on flights." Return an empty list if nothing qualifies."""

SCHEMA = {
    "type": "object",
    "properties": {"memories": {"type": "array", "items": {"type": "string"}}},
    "required": ["memories"],
}

_SENSITIVE = re.compile(r"\b(?:\d[ -]?){13,19}\b|password|passcode|\bcvv\b|\bpin\b|aadhaar|\bssn\b|passport", re.I)


def save(session: Session, user: User, text: str, source: str = "stated") -> Memory | None:
    text = text.strip()[:400]
    if not text or _SENSITIVE.search(text):
        return None
    if any(_norm(text) == _norm(m) for _, m in all_memories(session, user)):
        return None
    m = Memory(user_id=user.id, text_enc=encrypt(user.id, text), source=source)
    session.add(m)
    session.flush()
    return m


def all_memories(session: Session, user: User) -> list[tuple[int, str]]:
    rows = session.scalars(select(Memory).where(Memory.user_id == user.id).order_by(Memory.created_at.desc())).all()
    return [(m.id, decrypt(user.id, m.text_enc) or "") for m in rows]


def forget(session: Session, user: User, query: str) -> int:
    q = query.lower().strip()
    n = 0
    for mid, text in all_memories(session, user):
        if q and q in text.lower():
            session.delete(session.get(Memory, mid))
            n += 1
    return n


def delete(session: Session, user: User, memory_id: int) -> bool:
    m = session.get(Memory, memory_id)
    if m and m.user_id == user.id:
        session.delete(m)
        return True
    return False


def prompt_block(session: Session, user: User) -> str:
    mems = all_memories(session, user)[:MAX_MEMORIES_IN_PROMPT]
    return "\n".join(f"- {t}" for _, t in mems) or "- nothing yet"


def learn_from_message(session: Session, user: User, message: str, llm: LLM) -> list[str]:
    """Background memory pass over a user's message. Cheap model; failures are ignored."""
    if len(message) < 25 or message.strip().lower().startswith(("yes", "no", "ok", "skip", "edit")):
        return []
    known = prompt_block(session, user)
    try:
        result = llm.extract(SYSTEM, f"Known memories:\n{known}\n\nNew message from the person:\n{message[:2000]}",
                             "remember", SCHEMA)
    except Exception:  # noqa: BLE001
        log.exception("memory extraction failed")
        return []
    saved = []
    for text in (result.get("memories") or [])[:5]:
        if save(session, user, text, source="chat"):
            saved.append(text)
    return saved


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
