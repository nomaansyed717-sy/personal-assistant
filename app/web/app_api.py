"""App-first API: sign-in by email or SMS code, in-app onboarding, push devices, uploads, Today.

Used by both the Android app (bearer tokens) and the web app (session cookie). Signing in with a
new email or phone number creates the account: there is no separate sign-up.
"""
import hmac
import logging
import re
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import push
from app.agent import actions, onboarding
from app.agent.router import route
from app.audit import audit
from app.brief import todays_events
from app.config import get_settings
from app.context.rank import top_open
from app.crypto import encrypt
from app.db import session_scope, utcnow
from app.integrations import google
from app.llm import get_llm
from app.media import MediaError, prepare_bytes
from app.messenger import record_inbound
from app.models import Connection, Goal, LoginCode, Message, StandingTask, Subscription, User
from app.otp import DeliveryError, send_email_code, send_sms_code
from app.util import aware, guess_timezone, normalize_phone, zone
from app.web.api import _csrf, _hash, _locks, _start_session, current_user_id, session_token

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")
CODE_MINUTES = 10
MAX_LIVE_CODES = 3
APP_SESSION_DAYS = 90


# ------------------------------------------------------------------ sign-in by code


class AuthStart(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    tz: str | None = Field(default=None, max_length=64)  # the device's time zone, for new accounts


class AuthVerify(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    code: str = Field(min_length=4, max_length=8)
    client: str = Field(default="web", pattern="^(web|app)$")


def _identity(email: str | None, phone: str | None) -> tuple[str | None, str | None]:
    if email:
        e = email.strip().lower()
        if not EMAIL.match(e):
            raise HTTPException(status_code=400, detail="That doesn't look like an email address.")
        return e, None
    if phone:
        p = normalize_phone(phone)
        if not re.fullmatch(r"\+\d{8,15}", p):
            raise HTTPException(status_code=400, detail="Enter the number with its country code, e.g. +91 98765 43210.")
        return None, p
    raise HTTPException(status_code=400, detail="Enter an email address or a phone number.")


def _find(s, email: str | None, phone: str | None) -> User | None:
    if email:
        return s.scalar(select(User).where(func.lower(User.email) == email, User.demo.is_(False)).order_by(User.id))
    return s.scalar(select(User).where(User.phone == phone))


def _valid_tz(tz: str | None) -> str | None:
    if not tz:
        return None
    return tz if zone(tz).key == tz else None


@router.post("/auth/start")
def auth_start(body: AuthStart, request: Request):
    """Send a 6-digit code. Creates the account on first use."""
    if not request.headers.get("authorization"):
        _csrf(request)
    email, phone = _identity(body.email, body.phone)
    with session_scope() as s:
        user = _find(s, email, phone)
        if user is None:
            tz = _valid_tz(body.tz) or (guess_timezone(phone) if phone else "UTC")
            user = User(email=email, phone=phone, timezone=tz, channel="app", onboarding_state="new",
                        assistant_name=get_settings().app_name, brief_hour=get_settings().default_brief_hour)
            s.add(user)
            s.flush()
            audit(s, user.id, "signup", "email" if email else "sms", actor="user")
        live = s.scalar(select(func.count(LoginCode.id)).where(LoginCode.user_id == user.id, LoginCode.used.is_(False),
                                                               LoginCode.expires_at > utcnow()))
        if live >= MAX_LIVE_CODES:
            raise HTTPException(status_code=429, detail="Too many codes. Use the last one we sent, or wait 10 minutes.")
        code = f"{secrets.randbelow(1_000_000):06d}"
        s.add(LoginCode(user_id=user.id, code_hash=_hash(code), expires_at=utcnow() + timedelta(minutes=CODE_MINUTES)))
        try:
            send_email_code(email, code) if email else send_sms_code(phone, code)
        except DeliveryError as exc:
            raise HTTPException(status_code=503, detail="We couldn't send the code. Please try again shortly.") from exc
    return {"ok": True, "sent_to": "email" if email else "sms"}


@router.post("/auth/verify")
def auth_verify(body: AuthVerify, request: Request, response: Response):
    if body.client == "web":
        _csrf(request)
    email, phone = _identity(body.email, body.phone)
    with session_scope() as s:
        user = _find(s, email, phone)
        if not user:
            raise HTTPException(status_code=400, detail="Wrong or expired code.")
        codes = s.scalars(select(LoginCode).where(LoginCode.user_id == user.id, LoginCode.used.is_(False),
                                                  LoginCode.expires_at > utcnow())).all()
        ok = None
        for c in codes:
            c.attempts += 1
            if c.attempts <= 5 and hmac.compare_digest(c.code_hash, _hash(body.code.strip())):
                ok = c
        if not ok:
            raise HTTPException(status_code=400, detail="Wrong or expired code.")
        ok.used = True
        if user.onboarding_state == "new":
            user.onboarding_state = "awaiting_consent"
        audit(s, user.id, "app_login" if body.client == "app" else "web_login", "", actor="user")
        state = user.onboarding_state
        if body.client == "app":
            token = secrets.token_urlsafe(32)
            from app.models import WebSession

            s.add(WebSession(token_hash=_hash(token), user_id=user.id,
                             expires_at=utcnow() + timedelta(days=APP_SESSION_DAYS)))
            return {"ok": True, "token": token, "onboarding_state": state}
        _start_session(s, user.id, response)
    return {"ok": True, "onboarding_state": state}


# ------------------------------------------------------------------ onboarding


class ConsentIn(BaseModel):
    accept: bool
    name: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)


@router.post("/onboarding/consent")
def onboarding_consent(body: ConsentIn, uid: int = Depends(current_user_id)):
    if not body.accept:
        raise HTTPException(status_code=400, detail="You need to agree to the terms to use the assistant.")
    with session_scope() as s:
        user = s.get(User, uid)
        if body.name and body.name.strip():
            user.name = body.name.strip()
        if tz := _valid_tz(body.timezone):
            user.timezone = tz
        onboarding.accept_terms(s, user)
        return {"onboarding_state": user.onboarding_state}


class ConnectIn(BaseModel):
    client: str = Field(default="web", pattern="^(web|app)$")


@router.post("/onboarding/google")
def onboarding_google(body: ConnectIn, uid: int = Depends(current_user_id)):
    """A one-time Google consent link. Works during onboarding and later from Settings."""
    if not get_settings().google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in isn't set up on this server yet.")
    with session_scope() as s:
        user = s.get(User, uid)
        if user.demo:
            raise HTTPException(status_code=400, detail="The demo uses a sample inbox.")
        if user.onboarding_state in ("new", "awaiting_consent"):
            raise HTTPException(status_code=400, detail="Agree to the terms first.")
        return {"url": google.start_url(s, uid, return_to=body.client)}


@router.post("/onboarding/skip")
def onboarding_skip(uid: int = Depends(current_user_id)):
    with session_scope() as s:
        user = s.get(User, uid)
        onboarding.skip_connect(s, user)
        return {"onboarding_state": user.onboarding_state}


@router.delete("/connections/google")
def disconnect_google(uid: int = Depends(current_user_id)):
    from app.agent.account import revoke

    with session_scope() as s:
        conn = s.scalar(select(Connection).where(Connection.user_id == uid, Connection.provider == "google"))
        if not conn:
            raise HTTPException(status_code=404)
        revoke(conn)
        s.delete(conn)
        audit(s, uid, "disconnected", "google", actor="user")
        return {"ok": True}


# ------------------------------------------------------------------ push devices


class DeviceIn(BaseModel):
    token: str = Field(min_length=10, max_length=255)
    platform: str = Field(default="android", pattern="^(android|ios|web)$")


@router.post("/devices")
def add_device(body: DeviceIn, uid: int = Depends(current_user_id)):
    if not body.token.startswith(("ExponentPushToken[", "ExpoPushToken[")):
        raise HTTPException(status_code=400, detail="not an Expo push token")
    with session_scope() as s:
        push.register(s, s.get(User, uid), body.token, body.platform)
        return {"ok": True}


@router.post("/devices/remove")
def remove_device(body: DeviceIn, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        return {"removed": push.unregister(s, s.get(User, uid), body.token)}


# ------------------------------------------------------------------ chat with attachments


@router.post("/chat/upload")
async def chat_upload(request: Request, file: UploadFile = File(...), caption: str = Form(default=""),
                      voice: bool = Form(default=False), uid: int = Depends(current_user_id)):
    """A photo, PDF, text file or voice note from the app, with an optional caption."""
    data = await file.read()
    with _locks[uid], session_scope() as s:
        user = s.get(User, uid)
        if user.onboarding_state != "active":
            raise HTTPException(status_code=400, detail="Finish setting up first.")
        try:
            text, attachments = prepare_bytes(data, file.content_type, caption[:2000], file.filename, audio=voice,
                                              language=user.voice_language or "auto")
        except MediaError as exc:
            return {"reply": str(exc), "transcript": None}
        shown = ("🎤 " + text) if voice else (caption or f"📎 {file.filename or 'attachment'}")
        record_inbound(s, user, shown, None, "app")
        try:
            reply = route(s, user, text, get_llm(), attachments) or ""
        except Exception:  # noqa: BLE001
            log.exception("upload chat failed for user %s", uid)
            reply = "I couldn't reach my AI model just now. Please try again in a minute."
        if reply:
            s.add(Message(user_id=uid, direction="out", channel="app", body_enc=encrypt(uid, reply)))
        return {"reply": reply, "transcript": text if voice else None}


# ------------------------------------------------------------------ Today


@router.get("/today")
def today(uid: int = Depends(current_user_id)):
    """Everything the home screen needs in one call."""
    with session_scope() as s:
        user = s.get(User, uid)
        tz = zone(user.timezone)
        events = [{"title": e.subject or "(no title)", "start": aware(e.occurred_at).astimezone(tz).isoformat(),
                   "end": aware(e.ends_at).astimezone(tz).isoformat() if e.ends_at else None}
                  for e in todays_events(s, user)]
        loops = [{"id": c.id, "direction": c.direction, "description": c.description,
                  "person": c.person.name or c.person.email if c.person else None,
                  "due_at": aware(c.due_at).isoformat() if c.due_at else None}
                 for c in top_open(s, uid, limit=get_settings().brief_max_items)]
        approvals = len(actions.open_proposals(s, uid))
        goals = s.scalars(select(Goal).where(Goal.user_id == uid, Goal.status == "active").order_by(Goal.created_at)
                          .limit(5)).all()
        tasks = s.scalar(select(func.count(StandingTask.id)).where(StandingTask.user_id == uid,
                                                                   StandingTask.status == "active"))
        subs = s.scalars(select(Subscription).where(Subscription.user_id == uid, Subscription.status == "active")).all()
        monthly = {}
        for x in subs:
            if x.amount:
                per_month = x.amount / 12 if x.cadence == "yearly" else x.amount * 4.33 if x.cadence == "weekly" else x.amount
                monthly[x.currency or "INR"] = monthly.get(x.currency or "INR", 0) + per_month
        hour = utcnow().astimezone(tz).hour
        greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
        return {"greeting": f"{greeting}{', ' + user.name.split(' ')[0] if user.name else ''}",
                "assistant_name": user.assistant_name, "events": events, "loops": loops, "approvals": approvals,
                "goals": [{"id": g.id, "title": g.title, "progress_note": g.progress_note} for g in goals],
                "standing_tasks": tasks, "subscriptions_monthly": {k: round(v) for k, v in monthly.items()},
                "paused": user.paused}


class LoopAction(BaseModel):
    action: str = Field(pattern="^(done|snooze)$")
    days: int = Field(default=3, ge=1, le=60)


@router.post("/loops/{cid}")
def loop_action(cid: int, body: LoopAction, uid: int = Depends(current_user_id)):
    from app.context.rank import snooze
    from app.models import Commitment

    with session_scope() as s:
        c = s.get(Commitment, cid)
        if not c or c.user_id != uid:
            raise HTTPException(status_code=404)
        if body.action == "done":
            c.status = "done"
            audit(s, uid, "loop_done", c.description[:200], actor="user")
        else:
            snooze(c, body.days)
            audit(s, uid, "loop_snoozed", f"{body.days} days", actor="user")
        return {"ok": True}


@router.post("/logout/app")
def logout_app(request: Request, uid: int = Depends(current_user_id)):
    """Sign this device out: drop its session and stop its pushes."""
    from app.models import Device, WebSession

    token = session_token(request) or ""
    with session_scope() as s:
        ws = s.scalar(select(WebSession).where(WebSession.token_hash == _hash(token)))
        if ws:
            s.delete(ws)
        push_token = request.headers.get("x-push-token")
        if push_token:
            dev = s.scalar(select(Device).where(Device.push_token == push_token, Device.user_id == uid))
            if dev:
                s.delete(dev)
    return {"ok": True}
