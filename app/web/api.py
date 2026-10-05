"""JSON API behind the web app (phone and Mac browsers).

Sign-in: the user enters their WhatsApp number, gets a 6-digit code on WhatsApp, and receives an
httpOnly session cookie. Only people who have already messaged the assistant can sign in.
Every state-changing request must carry the X-Requested-With header (CSRF defence together with
SameSite=Strict cookies).
"""
import hashlib
import hmac
import secrets
import threading
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import skills, standing, vault
from app.agent import account, actions
from app.agent.router import route
from app.audit import audit
from app.config import get_settings
from app.context import memory
from app.crypto import decrypt
from app.db import session_scope, utcnow
from app.llm import get_llm
from app.messenger import record_inbound, send
from app.models import (
    Action,
    AuditLog,
    Goal,
    LoginCode,
    Message,
    StandingTask,
    Subscription,
    User,
    WebSession,
)
from app.util import aware, normalize_phone

router = APIRouter(prefix="/api")
COOKIE = "aide_session"
SESSION_DAYS = 30
_locks: dict[int, threading.Lock] = defaultdict(threading.Lock)


def _hash(v: str) -> str:
    key = (get_settings().master_key or "dev").encode()
    return hmac.new(key, v.encode(), hashlib.sha256).hexdigest()


def _csrf(request: Request) -> None:
    if request.method not in ("GET", "HEAD") and request.headers.get("x-requested-with") != "aide":
        raise HTTPException(status_code=403, detail="missing CSRF header")


def current_user_id(request: Request) -> int:
    _csrf(request)
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="sign in")
    with session_scope() as s:
        ws = s.scalar(select(WebSession).where(WebSession.token_hash == _hash(token)))
        if not ws or aware(ws.expires_at) < utcnow():
            raise HTTPException(status_code=401, detail="session expired")
        return ws.user_id


# ------------------------------------------------------------------ auth


class LoginStart(BaseModel):
    phone: str = Field(max_length=32)


class LoginVerify(BaseModel):
    phone: str = Field(max_length=32)
    code: str = Field(max_length=8)


@router.post("/login/start")
def login_start(body: LoginStart, request: Request):
    _csrf(request)
    phone = normalize_phone(body.phone)
    with session_scope() as s:
        user = s.scalar(select(User).where(User.phone == phone))
        # Same answer either way, so the endpoint can't be used to discover who is a user.
        if user and user.onboarding_state != "new":
            recent = s.scalars(select(LoginCode).where(LoginCode.user_id == user.id,
                                                       LoginCode.expires_at > utcnow() + timedelta(minutes=9))).all()
            if len(recent) < 3:
                code = f"{secrets.randbelow(1_000_000):06d}"
                s.add(LoginCode(user_id=user.id, code_hash=_hash(code), expires_at=utcnow() + timedelta(minutes=10)))
                send(s, user, f"Your {get_settings().app_name} sign-in code is *{code}*. It expires in 10 minutes. "
                              "Never share it with anyone.")
    return {"ok": True, "note": "If this number uses the assistant, a code is on its way to WhatsApp."}


@router.post("/login/verify")
def login_verify(body: LoginVerify, request: Request, response: Response):
    _csrf(request)
    phone = normalize_phone(body.phone)
    with session_scope() as s:
        user = s.scalar(select(User).where(User.phone == phone))
        if not user:
            raise HTTPException(status_code=400, detail="wrong or expired code")
        codes = s.scalars(select(LoginCode).where(LoginCode.user_id == user.id, LoginCode.used.is_(False),
                                                  LoginCode.expires_at > utcnow())).all()
        ok = None
        for c in codes:
            c.attempts += 1
            if c.attempts <= 5 and hmac.compare_digest(c.code_hash, _hash(body.code.strip())):
                ok = c
        if not ok:
            raise HTTPException(status_code=400, detail="wrong or expired code")
        ok.used = True
        token = secrets.token_urlsafe(32)
        s.add(WebSession(token_hash=_hash(token), user_id=user.id, expires_at=utcnow() + timedelta(days=SESSION_DAYS)))
        audit(s, user.id, "web_login", "", actor="user")
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="strict",
                        secure=get_settings().base_url.startswith("https"))
    return {"ok": True}


def _start_session(s, user_id: int, response: Response, days: int = SESSION_DAYS) -> None:
    token = secrets.token_urlsafe(32)
    s.add(WebSession(token_hash=_hash(token), user_id=user_id, expires_at=utcnow() + timedelta(days=days)))
    response.set_cookie(COOKIE, token, max_age=days * 86400, httponly=True, samesite="strict",
                        secure=get_settings().base_url.startswith("https"))


# ------------------------------------------------------------------ live demo


class DemoStart(BaseModel):
    tz: str = Field(default="Asia/Kolkata", max_length=64)


def _client_ip(request: Request) -> str:
    return (request.client.host if request.client else "") or "unknown"


@router.post("/demo/start")
def demo_start(body: DemoStart, request: Request, response: Response):
    from app import demo

    _csrf(request)
    if not get_settings().demo_enabled:
        raise HTTPException(status_code=404, detail="the demo is switched off")
    if not demo.allow_new_demo(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many demos from here. Try again in an hour.")
    with session_scope() as s:
        user = demo.create_demo_user(s, body.tz, get_settings().app_name)
        uid = user.id
        audit(s, uid, "demo_started", "", actor="user")
        _start_session(s, uid, response, days=1)
    demo.start_run(uid, "welcome")
    return {"ok": True}


def _demo_uid(uid: int) -> int:
    with session_scope() as s:
        u = s.get(User, uid)
        if not u or not u.demo:
            raise HTTPException(status_code=404, detail="not a demo account")
    return uid


@router.get("/demo/status")
def demo_status(uid: int = Depends(current_user_id)):
    from app import demo

    return demo.status(_demo_uid(uid))


class DemoRun(BaseModel):
    what: str = Field(pattern="^(brief|email|tasks|ideas)$")


@router.post("/demo/run")
def demo_run(body: DemoRun, uid: int = Depends(current_user_id)):
    from app import demo

    if not demo.start_run(_demo_uid(uid), body.what):
        raise HTTPException(status_code=409, detail="Still working on the last step, or this demo has used all its runs.")
    return demo.status(uid)


@router.get("/demo/world")
def demo_world(uid: int = Depends(current_user_id)):
    from app import demo

    _demo_uid(uid)
    with session_scope() as s:
        tz = s.get(User, uid).timezone
    w = demo.world_for(uid, tz)
    return {"inbox": w.inbox(), "calendar": w.calendar(), "sent": w.sent_by_assistant}


@router.post("/demo/reset")
def demo_reset(request: Request, response: Response, uid: int = Depends(current_user_id)):
    from app import demo

    _demo_uid(uid)
    with session_scope() as s:
        tz = s.get(User, uid).timezone
        demo.delete_demo_user(s, uid)
    with session_scope() as s:
        user = demo.create_demo_user(s, tz, get_settings().app_name)
        new_uid = user.id
        _start_session(s, new_uid, response, days=1)
    demo.start_run(new_uid, "welcome")
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response, uid: int = Depends(current_user_id)):
    token = request.cookies.get(COOKIE, "")
    with session_scope() as s:
        ws = s.scalar(select(WebSession).where(WebSession.token_hash == _hash(token)))
        if ws:
            s.delete(ws)
    response.delete_cookie(COOKIE)
    return {"ok": True}


# ------------------------------------------------------------------ me + chat


@router.get("/me")
def me(uid: int = Depends(current_user_id)):
    with session_scope() as s:
        u = s.get(User, uid)
        return {"name": u.name, "assistant_name": u.assistant_name, "persona": u.persona, "timezone": u.timezone,
                "brief_hour": u.brief_hour, "ideas_enabled": u.ideas_enabled, "training_opt_in": u.training_opt_in,
                "paused": u.paused, "onboarding_state": u.onboarding_state, "demo": bool(u.demo),
                "phone": "demo" if u.demo else u.phone[:-4] + "••••"}


@router.get("/messages")
def messages(uid: int = Depends(current_user_id), limit: int = 60):
    with session_scope() as s:
        rows = s.scalars(select(Message).where(Message.user_id == uid, Message.direction.in_(["in", "out"]))
                         .order_by(Message.at.desc(), Message.id.desc()).limit(min(limit, 200))).all()
        return [{"id": m.id, "from": "me" if m.direction == "in" else "assistant", "channel": m.channel,
                 "text": decrypt(uid, m.body_enc) or "", "at": aware(m.at).isoformat()} for m in reversed(rows)]


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.post("/chat")
def chat(body: ChatIn, uid: int = Depends(current_user_id)):
    from app import demo
    from app.crypto import encrypt

    with _locks[uid], session_scope() as s:
        user = s.get(User, uid)
        if not demo.chat_allowed(s, user, get_settings().demo_messages):
            return {"reply": "This demo has used all its messages. Tap *Start over* for a fresh one, or sign up to keep going."}
        record_inbound(s, user, body.text, None, "web")
        reply = route(s, user, body.text, get_llm()) or ""
        if reply.startswith("\x00deleted:"):
            return {"reply": "Everything is deleted.", "deleted": True}
        if reply:  # web replies are returned directly (and kept in history), not sent to WhatsApp
            s.add(Message(user_id=uid, direction="out", channel="web", body_enc=encrypt(uid, reply)))
        return {"reply": reply}


# ------------------------------------------------------------------ approvals + activity


@router.get("/approvals")
def approvals(uid: int = Depends(current_user_id)):
    with session_scope() as s:
        return [{"id": a.id, "number": a.number, "kind": a.kind, "tier": a.tier, "preview": a.preview,
                 "payload": a.payload, "created_at": aware(a.created_at).isoformat()}
                for a in actions.open_proposals(s, uid)]


def _own_action(s, uid: int, action_id: int) -> Action:
    a = s.get(Action, action_id)
    if not a or a.user_id != uid or a.status != "proposed":
        raise HTTPException(status_code=404, detail="not open")
    return a


@router.post("/approvals/{action_id}/approve")
def approve(action_id: int, uid: int = Depends(current_user_id)):
    with _locks[uid], session_scope() as s:
        a = _own_action(s, uid, action_id)
        return {"result": actions.approve(s, s.get(User, uid), a)}


@router.post("/approvals/{action_id}/reject")
def reject(action_id: int, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        a = _own_action(s, uid, action_id)
        actions.reject(s, s.get(User, uid), a)
        return {"ok": True}


@router.get("/activity")
def activity(uid: int = Depends(current_user_id), days: int = 7):
    with session_scope() as s:
        rows = s.scalars(select(AuditLog).where(AuditLog.user_id == uid,
                                                AuditLog.at >= utcnow() - timedelta(days=min(days, 90)))
                         .order_by(AuditLog.at.desc()).limit(300)).all()
        done = [{"at": aware(r.at).isoformat(), "actor": r.actor, "action": r.action,
                 "label": account.LABELS.get(r.action, r.action.replace("_", " ")), "detail": r.detail} for r in rows]
        planned_actions = s.scalars(select(Action).where(Action.user_id == uid, Action.status.in_(["proposed", "scheduled"]))
                                    .order_by(Action.created_at)).all()
        tasks = s.scalars(select(StandingTask).where(StandingTask.user_id == uid, StandingTask.status == "active")
                          .order_by(StandingTask.next_run_at)).all()
        planned = ([{"when": "now" if a.status == "scheduled" else "after your yes", "what": a.preview.splitlines()[0]}
                    for a in planned_actions]
                   + [{"when": aware(t.next_run_at).isoformat() if t.next_run_at else "", "what": t.title} for t in tasks])
        return {"planned": planned, "done": done}


# ------------------------------------------------------------------ memory, goals, tasks, skills, money


@router.get("/memories")
def memories(uid: int = Depends(current_user_id)):
    with session_scope() as s:
        return [{"id": i, "text": t} for i, t in memory.all_memories(s, s.get(User, uid))]


@router.delete("/memories/{mid}")
def delete_memory(mid: int, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        if not memory.delete(s, s.get(User, uid), mid):
            raise HTTPException(status_code=404)
        audit(s, uid, "forgot", "1 memory", actor="user")
        return {"ok": True}


class MemoryIn(BaseModel):
    text: str = Field(min_length=3, max_length=400)


@router.post("/memories")
def add_memory(body: MemoryIn, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        m = memory.save(s, s.get(User, uid), body.text, source="stated")
        if not m:
            raise HTTPException(status_code=400, detail="duplicate or sensitive")
        return {"id": m.id}


class GoalIn(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    detail: str | None = Field(default=None, max_length=2000)
    target_date: date | None = None


class GoalPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^(active|paused|done)$")
    progress_note: str | None = Field(default=None, max_length=1000)


@router.get("/goals")
def goals(uid: int = Depends(current_user_id)):
    with session_scope() as s:
        rows = s.scalars(select(Goal).where(Goal.user_id == uid).order_by(Goal.status, Goal.created_at)).all()
        return [{"id": g.id, "title": g.title, "detail": g.detail, "status": g.status, "progress_note": g.progress_note,
                 "target_date": g.target_date.isoformat() if g.target_date else None} for g in rows]


@router.post("/goals")
def add_goal(body: GoalIn, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        g = Goal(user_id=uid, title=body.title, detail=body.detail, target_date=body.target_date)
        s.add(g)
        s.flush()
        audit(s, uid, "goal_added", g.title, actor="user")
        return {"id": g.id}


@router.patch("/goals/{gid}")
def patch_goal(gid: int, body: GoalPatch, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        g = s.get(Goal, gid)
        if not g or g.user_id != uid:
            raise HTTPException(status_code=404)
        if body.status:
            g.status = body.status
        if body.progress_note is not None:
            g.progress_note = body.progress_note
        return {"ok": True}


class TaskIn(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    instruction: str = Field(min_length=5, max_length=4000)
    schedule: str = Field(max_length=64)


@router.get("/tasks")
def tasks(uid: int = Depends(current_user_id)):
    with session_scope() as s:
        rows = s.scalars(select(StandingTask).where(StandingTask.user_id == uid).order_by(StandingTask.status,
                                                                                         StandingTask.next_run_at)).all()
        return [{"id": t.id, "title": t.title, "instruction": t.instruction, "schedule": t.schedule, "status": t.status,
                 "next_run_at": aware(t.next_run_at).isoformat() if t.next_run_at else None,
                 "last_result": t.last_result, "runs": t.runs} for t in rows]


@router.post("/tasks")
def add_task(body: TaskIn, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        instr = body.instruction
        if "NOTHING_NEW" not in instr:
            instr += " If there is nothing worth telling me, reply exactly NOTHING_NEW."
        try:
            t = standing.create(s, s.get(User, uid), body.title, instr, body.schedule)
        except standing.ScheduleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": t.id}


@router.delete("/tasks/{tid}")
def stop_task(tid: int, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        t = s.get(StandingTask, tid)
        if not t or t.user_id != uid:
            raise HTTPException(status_code=404)
        t.status, t.next_run_at = "done", None
        audit(s, uid, "task_cancelled", t.title, actor="user")
        return {"ok": True}


class SkillIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=3, max_length=255)
    instructions: str = Field(min_length=10, max_length=4000)


@router.get("/skills")
def list_skills(uid: int = Depends(current_user_id)):
    with session_scope() as s:
        return skills.all_skills(s, s.get(User, uid))


@router.post("/skills")
def add_skill(body: SkillIn, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        sk = skills.create(s, s.get(User, uid), body.name, body.description, body.instructions)
        audit(s, uid, "skill_created", sk.name, actor="user")
        return {"name": sk.name}


@router.delete("/skills/{sid}")
def delete_skill(sid: int, uid: int = Depends(current_user_id)):
    from app.models import Skill

    with session_scope() as s:
        sk = s.get(Skill, sid)
        if not sk or sk.user_id != uid:
            raise HTTPException(status_code=404)
        s.delete(sk)
        return {"ok": True}


@router.get("/subscriptions")
def subscriptions(uid: int = Depends(current_user_id)):
    with session_scope() as s:
        rows = s.scalars(select(Subscription).where(Subscription.user_id == uid).order_by(Subscription.merchant)).all()
        return [{"id": x.id, "merchant": x.merchant, "amount": x.amount, "currency": x.currency, "cadence": x.cadence,
                 "status": x.status} for x in rows]


# ------------------------------------------------------------------ vault


class VaultIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    site: str = Field(min_length=3, max_length=255)
    username: str = Field(min_length=1, max_length=255)
    secret: str = Field(min_length=1, max_length=512)


@router.get("/vault")
def vault_list(uid: int = Depends(current_user_id)):
    with session_scope() as s:
        return vault.listing(s, s.get(User, uid))


@router.post("/vault")
def vault_add(body: VaultIn, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        item = vault.add(s, s.get(User, uid), body.label, body.site, body.username, body.secret)
        return {"id": item.id}


@router.delete("/vault/{vid}")
def vault_delete(vid: int, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        if not vault.remove(s, s.get(User, uid), vid):
            raise HTTPException(status_code=404)
        return {"ok": True}


# ------------------------------------------------------------------ settings


class SettingsIn(BaseModel):
    assistant_name: str | None = Field(default=None, max_length=60)
    persona: str | None = Field(default=None, max_length=500)
    timezone: str | None = Field(default=None, max_length=64)
    brief_hour: int | None = Field(default=None, ge=0, le=23)
    ideas_enabled: bool | None = None
    training_opt_in: bool | None = None
    paused: bool | None = None


@router.patch("/settings")
def update_settings(body: SettingsIn, uid: int = Depends(current_user_id)):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    with session_scope() as s:
        u = s.get(User, uid)
        if body.timezone:
            try:
                ZoneInfo(body.timezone)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="unknown time zone") from exc
            u.timezone = body.timezone
        for field in ("assistant_name", "persona", "brief_hour", "ideas_enabled", "training_opt_in", "paused"):
            v = getattr(body, field)
            if v is not None:
                setattr(u, field, v.strip() if isinstance(v, str) else v)
        if body.training_opt_in is not None:
            from app.models import Consent

            s.add(Consent(user_id=uid, scope="training", granted=body.training_opt_in))
        audit(s, uid, "settings", ", ".join(k for k, v in body.model_dump().items() if v is not None), actor="user")
        return {"ok": True}
