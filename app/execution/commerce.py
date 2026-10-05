"""Purchases. The assistant researches, compares and prepares; the person pays.

Muse issues one-time virtual card numbers through a payments partner. Until we integrate a
card-issuing partner (e.g. Stripe Issuing), a purchase ends in a checkout handoff: the user gets
the exact product link and opens it themselves. No card data ever passes through the assistant.
"""
from sqlalchemy.orm import Session

from app.execution import register
from app.models import Action, User


@register("purchase")
def handoff(session: Session, user: User, action: Action) -> str:
    p = action.payload
    price = f" for {p['price']}" if p.get("price") else ""
    return f"Ready for you to check out: {p.get('item', 'your item')}{price} at {p.get('merchant', 'the store')}\n{p.get('url', '')}".strip()
