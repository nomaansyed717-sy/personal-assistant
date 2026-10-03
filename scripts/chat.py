"""Talk to the assistant in your terminal, without WhatsApp.

  python scripts/chat.py                 # uses your real Google connection and Claude key
  python scripts/chat.py --demo          # real Claude, but a sample mailbox instead of Gmail

Needs DATABASE_URL, MASTER_KEY and ANTHROPIC_API_KEY in .env. WHATSAPP_TOKEN must be empty.
"""
import argparse
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["WHATSAPP_TOKEN"] = ""

from sqlalchemy import select  # noqa: E402

from app import channels  # noqa: E402
from app.agent import onboarding  # noqa: E402
from app.channels import ConsoleChannel, InboundMessage  # noqa: E402
from app.crypto import encrypt  # noqa: E402
from app.db import init_db, session_scope, utcnow  # noqa: E402
from app.integrations import google  # noqa: E402
from app.llm import get_llm  # noqa: E402
from app.main import process_message  # noqa: E402
from app.models import Connection, User  # noqa: E402


def demo_mailbox():
    from tests.fakes import FakeGoogle

    g = FakeGoogle(account="you@example.com")
    t = utcnow()
    g.add_email("d0", "t0", "you@example.com", ["ravi@distrib.co"], "Order 4471", "Hi Ravi, confirming order 4471. Thanks", t - timedelta(days=25), sent=True)
    g.add_email("d1", "t1", "ravi@distrib.co", ["you@example.com"], "Revised GST invoice",
                "Hi, could you send the revised GST invoice for order 4471 by Friday? Our accounts team needs it. Thanks, Ravi",
                t - timedelta(days=4), from_name="Ravi Kumar")
    g.add_email("d2", "t2", "anika@seedfund.vc", ["you@example.com"], "Following up",
                "Great meeting last week. Could you share the updated deck and the Q3 numbers?", t - timedelta(days=6), from_name="Anika Rao")
    g.add_email("d3", "t2", "you@example.com", ["anika@seedfund.vc"], "Re: Following up",
                "Thanks Anika! I'll send both by Monday.", t - timedelta(days=5), sent=True)
    g.add_email("d4", "t3", "priya@printworks.com", ["you@example.com"], "Quote for 5,000 notebooks",
                "Hi, we'll send the final quote by Wednesday once the paper price is confirmed. Priya", t - timedelta(days=7), from_name="Priya")
    g.add_event("c1", "Weekly ops sync", t + timedelta(hours=2), attendees=["nomaan@example.com"])
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", default="+910000000001")
    ap.add_argument("--name", default="You")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    init_db()
    ch = ConsoleChannel()
    channels.set_channel(ch)
    if args.demo:
        g = demo_mailbox()
        google.set_http(g.client())
        with session_scope() as s:
            user = s.scalar(select(User).where(User.phone == args.phone))
            if user is None:
                user = User(phone=args.phone, name=args.name, timezone="Asia/Kolkata", onboarding_state="awaiting_connect")
                s.add(user)
                s.flush()
                s.add(Connection(user_id=user.id, provider="google", account_email="you@example.com",
                                 access_token_enc=encrypt(user.id, "demo"), refresh_token_enc=encrypt(user.id, "demo"),
                                 expires_at=utcnow() + timedelta(days=1)))
                s.flush()
                onboarding.after_connect(s, user, get_llm())

    print("Type a message (Ctrl-C to quit).")
    n = 0
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if text:
            n += 1
            process_message(InboundMessage(phone=args.phone, text=text, external_id=f"cli-{utcnow().timestamp()}-{n}",
                                           profile_name=args.name), "console")


if __name__ == "__main__":
    main()
