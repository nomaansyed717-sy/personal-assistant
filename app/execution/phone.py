"""Phone agent: an Android companion app using accessibility services (or a cloud Android instance) for app-only services. Phase 3. iOS stays on APIs, Shortcuts and the browser.

The interface is live so the agent, permissions and approvals already handle
this action kind end to end; only the executor body is pending.
"""
from sqlalchemy.orm import Session

from app.execution import NotAvailable, register
from app.models import Action, User


@register("phone_task")
def run(session: Session, user: User, action: Action) -> str:
    raise NotAvailable("phone_task is not switched on in this deployment yet")
