"""Browser agent on the user's signed-in sites (cab, travel, food, bill-pay). Phase 2. Planned implementation: a cloud browser per user with encrypted session cookies, computer-use model driving it, a screenshot check after every step, replayable per-site skills, and OTP relayed to the user over chat.

The interface is live so the agent, permissions and approvals already handle
this action kind end to end; only the executor body is pending.
"""
from sqlalchemy.orm import Session

from app.execution import NotAvailable, register
from app.models import Action, User


@register("browser_task")
def run(session: Session, user: User, action: Action) -> str:
    raise NotAvailable("browser_task is not switched on in this deployment yet")
