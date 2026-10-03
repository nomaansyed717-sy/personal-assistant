"""Database tables.

Raw content (email bodies, chat text, OAuth tokens) is stored encrypted with a
per-user key (app/crypto.py). Structured facts (people, projects,
commitments, preferences) are what the assistant reasons over and what the
user can inspect and delete from chat.
"""
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow

TS = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # E.164, e.g. +919876543210
    name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    language: Mapped[str | None] = mapped_column(String(32))
    # new -> awaiting_consent -> awaiting_connect -> syncing -> active
    onboarding_state: Mapped[str] = mapped_column(String(32), default="new")
    brief_hour: Mapped[int] = mapped_column(Integer, default=8)
    last_brief_on: Mapped[date | None] = mapped_column(Date)
    last_inbound_at: Mapped[datetime | None] = mapped_column(TS)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    voice_profile_enc: Mapped[str | None] = mapped_column(Text)  # how the user writes, learned from sent mail
    pending_confirmation: Mapped[str | None] = mapped_column(String(64))  # e.g. "delete_everything"
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    connections: Mapped[list["Connection"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(64))  # terms | gmail | calendar | training
    granted: Mapped[bool] = mapped_column(Boolean)
    policy_version: Mapped[str] = mapped_column(String(32), default="2026-10")
    at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))  # google
    account_email: Mapped[str | None] = mapped_column(String(255))
    scopes: Mapped[str] = mapped_column(Text, default="")
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(TS)
    last_sync_at: Mapped[datetime | None] = mapped_column(TS)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | revoked | error
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    user: Mapped[User] = relationship(back_populates="connections")


class Event(Base):
    """A raw item ingested from a connected source (an email, a calendar event)."""

    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("user_id", "source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))  # gmail | calendar
    external_id: Mapped[str] = mapped_column(String(255))
    thread_id: Mapped[str | None] = mapped_column(String(255), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # email_in | email_out | calendar
    from_addr: Mapped[str | None] = mapped_column(String(320))
    from_name: Mapped[str | None] = mapped_column(String(255))
    to_addrs: Mapped[list] = mapped_column(JSON, default=list)
    subject: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(TS, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(TS)
    body_enc: Mapped[str | None] = mapped_column(Text)  # purged after RAW_RETENTION_DAYS
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # message-id header, attendees, etc.
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    purged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Person(Base):
    __tablename__ = "people"
    __table_args__ = (UniqueConstraint("user_id", "email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    relationship_note: Mapped[str | None] = mapped_column(String(255))  # "distributor", "investor", ...
    importance: Mapped[float] = mapped_column(Float, default=0.3)  # 0..1, learned
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)  # user said "this person matters"
    messages_in: Mapped[int] = mapped_column(Integer, default=0)
    messages_out: Mapped[int] = mapped_column(Integer, default=0)
    last_contact_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(255))
    deadline: Mapped[datetime | None] = mapped_column(TS)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Commitment(Base):
    """A promise made by the user (user_owes) or to the user (owed_to_user)."""

    __tablename__ = "commitments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(16))  # user_owes | owed_to_user
    description: Mapped[str] = mapped_column(Text)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    source_event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))
    thread_id: Mapped[str | None] = mapped_column(String(255))
    made_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    due_at: Mapped[datetime | None] = mapped_column(TS)
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open | done | dismissed | snoozed
    snoozed_until: Mapped[datetime | None] = mapped_column(TS)
    last_surfaced_at: Mapped[datetime | None] = mapped_column(TS)
    times_surfaced: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    person: Mapped[Person | None] = relationship()
    project: Mapped[Project | None] = relationship()


class Preference(Base):
    """Stated preferences and hard rules ("never book flights before 7am")."""

    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="preference")  # preference | rule
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="stated")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Action(Base):
    """Something the assistant proposes or does. Every write to the outside world is an Action."""

    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    number: Mapped[int | None] = mapped_column(Integer)  # the number the user replies with ("1, 3")
    kind: Mapped[str] = mapped_column(String(32))  # send_email | create_event | ...
    tier: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    preview: Mapped[str] = mapped_column(Text)  # what the user sees before approving
    # proposed -> scheduled (undo window) -> executed | cancelled | rejected | failed | expired
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    origin: Mapped[str] = mapped_column(String(16), default="chat")  # brief | chat | routine
    commitment_id: Mapped[int | None] = mapped_column(ForeignKey("commitments.id", ondelete="SET NULL"))
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    execute_after: Mapped[datetime | None] = mapped_column(TS)
    executed_at: Mapped[datetime | None] = mapped_column(TS)
    result: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Delegation(Base):
    """Standing permission for one kind of action, granted explicitly by the user."""

    __tablename__ = "delegations"
    __table_args__ = (UniqueConstraint("user_id", "action_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action_kind: Mapped[str] = mapped_column(String(32))
    max_tier: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Message(Base):
    """Conversation history between the user and the assistant."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # in | out
    channel: Mapped[str] = mapped_column(String(16), default="whatsapp")
    body_enc: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(16))  # assistant | user | system
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")


class OAuthState(Base):
    """Short-lived state tokens that tie a Google OAuth callback to a user."""

    __tablename__ = "oauth_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
