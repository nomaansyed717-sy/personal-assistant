"""API for the phone agent: the Android app asks for the next step while it operates other apps.

Flow: a task is queued (the user typed a command on the Phone agent screen, or approved a phone_task the
assistant proposed in chat) -> the phone claims it -> loop: POST the screen to /step, carry out the action
-> the agent hands over for logins, OTPs and payments -> the user taps Resume -> ... -> done.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import phone_agent
from app.db import session_scope
from app.llm import get_llm
from app.models import PhoneJob, User
from app.web.api import _locks, current_user_id

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/phone")


def _own(s, uid: int, jid: int) -> PhoneJob:
    job = s.get(PhoneJob, jid)
    if not job or job.user_id != uid:
        raise HTTPException(status_code=404, detail="no such task")
    return job


class JobIn(BaseModel):
    goal: str = Field(min_length=3, max_length=2000)
    app: str | None = Field(default=None, max_length=120)


@router.post("/jobs")
def start_job(body: JobIn, uid: int = Depends(current_user_id)):
    """The user typed a command on the Phone agent screen: that is their go-ahead, so it starts right away."""
    with session_scope() as s:
        user = s.get(User, uid)
        if user.demo:
            raise HTTPException(status_code=400, detail="The phone agent works on your own phone, not in the demo.")
        try:
            job = phone_agent.create_job(s, user, body.goal, body.app)
        except phone_agent.PhoneAgentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return phone_agent.to_dict(job)


@router.get("/jobs")
def list_jobs(uid: int = Depends(current_user_id), limit: int = 20):
    with session_scope() as s:
        rows = s.scalars(select(PhoneJob).where(PhoneJob.user_id == uid).order_by(PhoneJob.created_at.desc())
                         .limit(min(limit, 50))).all()
        return [phone_agent.to_dict(j) for j in rows]


@router.get("/jobs/next")
def next_job(uid: int = Depends(current_user_id)):
    with session_scope() as s:
        job = phone_agent.next_queued(s, uid)
        return phone_agent.to_dict(job) if job else None


@router.get("/jobs/{jid}")
def get_job(jid: int, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        return phone_agent.to_dict(_own(s, uid, jid), steps=True)


class StepIn(BaseModel):
    screen: dict
    apps: list[dict] | None = None
    screenshot: str | None = Field(default=None, max_length=1_500_000)  # base64 JPEG, optional


@router.post("/jobs/{jid}/step")
def job_step(jid: int, body: StepIn, uid: int = Depends(current_user_id)):
    with _locks[uid], session_scope() as s:
        job = _own(s, uid, jid)
        return phone_agent.step(s, s.get(User, uid), job, body.screen, get_llm(), apps=body.apps,
                                screenshot=body.screenshot)


class EventIn(BaseModel):
    type: str = Field(pattern="^(started|resumed|stopped|error|action_failed)$")
    detail: str = Field(default="", max_length=1000)


@router.post("/jobs/{jid}/event")
def job_event(jid: int, body: EventIn, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        job = _own(s, uid, jid)
        phone_agent.event(s, s.get(User, uid), job, body.type, body.detail)
        return phone_agent.to_dict(job)
