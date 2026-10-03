"""Outbound voice calls: telephony provider + realtime voice model. The agent gets a call brief (goal, constraints, fallback), always discloses it is an AI assistant, follows each country's calling rules, and texts the user a one-line outcome plus the recording. Phase 2.

The interface is live so the agent, permissions and approvals already handle
this action kind end to end; only the executor body is pending.
"""
from sqlalchemy.orm import Session

from app.execution import NotAvailable, register
from app.models import Action, User


@register("phone_call")
def run(session: Session, user: User, action: Action) -> str:
    raise NotAvailable("phone_call is not switched on in this deployment yet")
