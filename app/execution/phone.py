"""Phone agent: Aide's Android app operates other apps on the user's phone (accessibility service).

Approving a phone_task queues a PhoneJob. The phone picks it up, reads the screen, asks the server for the
next step (app/phone_agent.py) and carries it out, stopping for logins, OTPs and payments, which stay the
user's. Nothing runs on the server's own browser for these: it all happens on the user's phone, in their
own signed-in apps.
"""
from sqlalchemy.orm import Session

from app import phone_agent
from app.execution import ExecutionError, register
from app.models import Action, User


@register("phone_task")
def run(session: Session, user: User, action: Action) -> str:
    p = action.payload or {}
    try:
        job = phone_agent.create_job(session, user, p.get("goal", ""), p.get("app"), action_id=action.id)
    except phone_agent.PhoneAgentError as exc:
        raise ExecutionError(str(exc)) from exc
    from app import push

    push.notify(session, user, f"Starting on your phone: {job.goal[:120]}", kind="phone_task")
    return (f"Starting on your phone: {job.goal[:160]}. Open Aide's Phone agent if it doesn't start on its own. "
            "I'll stop for you to sign in, and before any payment")
