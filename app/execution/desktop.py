"""Desktop agent: a small companion app on the user's Mac/PC that takes screenshots and clicks, for desktop-only software. Phase 2-3.

The interface is live so the agent, permissions and approvals already handle
this action kind end to end; only the executor body is pending.
"""
from sqlalchemy.orm import Session

from app.execution import NotAvailable, register
from app.models import Action, User


@register("desktop_task")
def run(session: Session, user: User, action: Action) -> str:
    raise NotAvailable("desktop_task is not switched on in this deployment yet")
