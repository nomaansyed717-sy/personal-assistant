from datetime import timedelta

from app.crypto import encrypt
from app.db import session_scope, utcnow
from app.models import Connection, Person, User

PHONE = "+14155550123"


def make_active_user(known=("ravi@distrib.com",), phone=PHONE, last_inbound_hours_ago=0.1) -> int:
    with session_scope() as s:
        u = User(
            phone=phone,
            name="Sam Lee",
            timezone="America/Los_Angeles",
            onboarding_state="active",
            last_inbound_at=utcnow() - timedelta(hours=last_inbound_hours_ago),
        )
        s.add(u)
        s.flush()
        s.add(
            Connection(
                user_id=u.id,
                provider="google",
                account_email="me@example.com",
                access_token_enc=encrypt(u.id, "at-old"),
                refresh_token_enc=encrypt(u.id, "rt-old"),
                expires_at=utcnow() + timedelta(hours=1),
            )
        )
        for email in known:
            s.add(Person(user_id=u.id, email=email, name=email.split("@")[0].title(), messages_out=3, messages_in=2))
        return u.id
