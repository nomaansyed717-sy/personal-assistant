"""API for automations (event triggers): list, create, pause, resume, remove, and the public webhook."""
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import triggers
from app.audit import audit
from app.db import session_scope
from app.models import Trigger, User
from app.web.api import current_user_id

log = logging.getLogger(__name__)
router = APIRouter()


def _own(s, uid: int, tid: int) -> Trigger:
    t = s.get(Trigger, tid)
    if not t or t.user_id != uid:
        raise HTTPException(status_code=404, detail="no such automation")
    return t


@router.get("/api/triggers")
def list_triggers(uid: int = Depends(current_user_id)):
    with session_scope() as s:
        rows = s.scalars(select(Trigger).where(Trigger.user_id == uid).order_by(Trigger.created_at)).all()
        return [triggers.public(t) for t in rows]


class TriggerIn(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    source: str = Field(pattern="^(email|webhook)$")
    instruction: str = Field(min_length=5, max_length=4000)
    match: dict = Field(default_factory=dict)


@router.post("/api/triggers")
def create_trigger(body: TriggerIn, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        try:
            t = triggers.create(s, s.get(User, uid), body.title, body.source, body.instruction, body.match)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return triggers.public(t)


@router.post("/api/triggers/{tid}/{op}")
def set_status(tid: int, op: str, uid: int = Depends(current_user_id)):
    if op not in ("pause", "resume"):
        raise HTTPException(status_code=404, detail="unknown action")
    with session_scope() as s:
        t = _own(s, uid, tid)
        t.status = "paused" if op == "pause" else "active"
        audit(s, uid, f"trigger_{op}d", t.title, actor="user")
        return triggers.public(t)


@router.delete("/api/triggers/{tid}")
def delete_trigger(tid: int, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        t = _own(s, uid, tid)
        audit(s, uid, "trigger_deleted", t.title, actor="user")
        s.delete(t)
    return {"ok": True}


def _fire_webhook(trigger_id: int, text: str) -> None:
    from app.agent.agent import run_background
    from app.llm import get_llm

    try:
        llm = get_llm()
        with session_scope() as s:
            t = s.get(Trigger, trigger_id)
            user = s.get(User, t.user_id) if t else None
            if t and user:
                triggers.fire(s, user, t, "webhook", text, lambda sess, u, p: run_background(sess, u, p, llm))
    except Exception:  # noqa: BLE001
        log.exception("webhook trigger %s failed", trigger_id)


@router.post("/hooks/{token}")
async def webhook(token: str, request: Request, background: BackgroundTasks):
    """Public: anything that knows the secret URL can start the automation. The body is data only."""
    raw = (await request.body())[: triggers.MAX_BODY]
    with session_scope() as s:
        t = s.scalar(select(Trigger).where(Trigger.token == token, Trigger.source == "webhook"))
        if t is None:
            raise HTTPException(status_code=404, detail="unknown hook")
        if t.status != "active":
            return {"ok": True, "status": "paused"}
        tid = t.id
    try:
        text = json.dumps(json.loads(raw), ensure_ascii=False, indent=1)
    except ValueError:
        text = raw.decode("utf-8", "replace")
    background.add_task(_fire_webhook, tid, text)
    return {"ok": True}
