"""Pull new mail and calendar events into the events table."""
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import get_settings
from app.context.people import touch, upsert_person
from app.crypto import encrypt
from app.db import utcnow
from app.integrations.google import GoogleClient, GoogleError
from app.models import Connection, Event, User
from app.util import aware

log = logging.getLogger(__name__)

GMAIL_FILTER = "-in:spam -in:trash -category:promotions -category:social -category:forums"


def google_client(session: Session, user: User) -> GoogleClient | None:
    conn = session.scalar(
        select(Connection).where(Connection.user_id == user.id, Connection.provider == "google", Connection.status == "active")
    )
    return GoogleClient(session, conn) if conn else None


def sync_user(session: Session, user: User, max_messages: int = 300) -> dict:
    client = google_client(session, user)
    if client is None:
        return {"skipped": "no google connection"}
    s = get_settings()
    conn = client.conn
    since = aware(conn.last_sync_at) - timedelta(hours=1) if conn.last_sync_at else utcnow() - timedelta(days=s.initial_sync_days)
    started = utcnow()
    stats = {"emails": 0, "events": 0}
    try:
        stats["emails"] = _sync_gmail(session, user, client, since, max_messages)
        stats["events"] = _sync_calendar(session, user, client)
    except GoogleError as exc:
        log.warning("sync failed for user %s: %s", user.id, exc)
        audit(session, user.id, "sync_failed", str(exc)[:300], actor="system")
        return {"error": str(exc)}
    conn.last_sync_at = started
    return stats


def _sync_gmail(session: Session, user: User, client: GoogleClient, since, max_messages: int) -> int:
    query = f"after:{int(since.timestamp())} {GMAIL_FILTER}"
    ids = client.list_message_ids(query, max_results=max_messages)
    if not ids:
        return 0
    known = set(
        session.scalars(
            select(Event.external_id).where(Event.user_id == user.id, Event.source == "gmail", Event.external_id.in_(ids))
        ).all()
    )
    own = (client.conn.account_email or "").lower()
    added = 0
    for msg_id in ids:
        if msg_id in known:
            continue
        m = client.get_message(msg_id)
        outgoing = m["sent"] or (own and m["from_addr"] == own)
        # Newsletters and receipts rarely hold commitments; keep them out of the ledger.
        if not outgoing and m["list_unsubscribe"]:
            continue
        session.add(
            Event(
                user_id=user.id,
                source="gmail",
                external_id=m["id"],
                thread_id=m["thread_id"],
                kind="email_out" if outgoing else "email_in",
                from_addr=m["from_addr"],
                from_name=m["from_name"],
                to_addrs=m["to"],
                subject=m["subject"],
                occurred_at=m["date"],
                body_enc=encrypt(user.id, m["body"] or m["snippet"]),
                meta={"message_id": m["message_id_header"]},
            )
        )
        if outgoing:
            for addr in m["to"]:
                if addr != own:
                    p = upsert_person(session, user.id, addr)
                    if p:
                        touch(p, m["date"], outgoing=True)
        else:
            p = upsert_person(session, user.id, m["from_addr"], m["from_name"])
            if p:
                touch(p, m["date"], outgoing=False)
        added += 1
    return added


def _sync_calendar(session: Session, user: User, client: GoogleClient) -> int:
    now = utcnow()
    events = client.list_events(now - timedelta(days=1), now + timedelta(days=14))
    count = 0
    for e in events:
        existing = session.scalar(
            select(Event).where(Event.user_id == user.id, Event.source == "calendar", Event.external_id == e["id"])
        )
        if existing is None:
            existing = Event(user_id=user.id, source="calendar", external_id=e["id"], kind="calendar", processed=True)
            session.add(existing)
            count += 1
        existing.subject = e["title"]
        existing.occurred_at = e["start"]
        existing.ends_at = e["end"]
        existing.to_addrs = e["attendees"]
        existing.meta = {"all_day": e["all_day"], "location": e["location"], "link": e["html_link"]}
        existing.body_enc = encrypt(user.id, e["description"]) if e["description"] else None
    return count
