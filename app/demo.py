"""Live demo: private sandbox accounts that run the real assistant against a simulated world.

Everything a demo visitor sees is produced by the same code real users get: inbox sync, commitment
extraction, the morning brief, the agent, approvals, standing tasks and ideas. Only the outside
world is replaced:

* Gmail and Google Calendar are an in-memory mailbox and calendar seeded with a realistic week.
  Emails the assistant "sends" land in that mailbox's Sent folder; nothing leaves the server.
* WhatsApp messages are stored and shown in the web app instead of being delivered.
* Web tasks and phone calls return a description of what would happen instead of running.

Demo accounts expire after DEMO_TTL and are rate limited, because every message costs model time.
"""
import base64
import json
import logging
import secrets
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from email import message_from_bytes

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import encrypt
from app.db import session_scope, utcnow
from app.models import Commitment, Connection, Goal, Message, Person, User
from app.util import zone

log = logging.getLogger(__name__)

DEMO_ACCOUNT = "sam@brightleaf.example"
DEMO_SCOPE = "demo"
DEMO_TTL = timedelta(hours=24)
MAX_DEMOS_PER_IP_PER_HOUR = 6
MAX_DEMOS_PER_DAY = 300
MAX_RUNS_PER_DEMO = 20


def is_demo_connection(conn: Connection | None) -> bool:
    return bool(conn and conn.scopes == DEMO_SCOPE)


# ------------------------------------------------------------------ simulated Gmail + Calendar


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


@dataclass
class DemoWorld:
    account: str = DEMO_ACCOUNT
    messages: dict[str, dict] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    sent_by_assistant: list[dict] = field(default_factory=list)
    created_events: list[dict] = field(default_factory=list)
    next_scenario: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add_email(self, mid, thread, frm, from_name, to, subject, body, when: datetime, sent=False, newsletter=False):
        headers = [
            {"name": "From", "value": f"{from_name} <{frm}>" if from_name else frm},
            {"name": "To", "value": ", ".join(to)},
            {"name": "Subject", "value": subject},
            {"name": "Date", "value": when.astimezone(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")},
            {"name": "Message-ID", "value": f"<{mid}@mail.example>"},
        ]
        if newsletter:
            headers.append({"name": "List-Unsubscribe", "value": "<mailto:unsubscribe@news.example>"})
        self.messages[mid] = {
            "id": mid, "threadId": thread, "labelIds": ["SENT"] if sent else ["INBOX"], "snippet": body[:90],
            "internalDate": str(int(when.timestamp() * 1000)),
            "payload": {"mimeType": "text/plain", "headers": headers, "body": {"data": _b64(body)}},
        }

    def add_event(self, eid, title, start: datetime, minutes=30, attendees=()):
        self.events.append({
            "id": eid, "status": "confirmed", "summary": title,
            "start": {"dateTime": start.isoformat()}, "end": {"dateTime": (start + timedelta(minutes=minutes)).isoformat()},
            "attendees": [{"email": a} for a in attendees],
        })

    # httpx transport: answers the exact Google endpoints app.integrations.google calls.
    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        with self.lock:
            if path == "/gmail/v1/users/me/messages" and method == "GET":
                return httpx.Response(200, json={"messages": [{"id": k} for k in self.messages]})
            if path.startswith("/gmail/v1/users/me/messages/") and method == "GET":
                msg = self.messages.get(path.rsplit("/", 1)[-1])
                return httpx.Response(200, json=msg) if msg else httpx.Response(404, json={"error": "not found"})
            if path == "/gmail/v1/users/me/messages/send":
                body = json.loads(request.content)
                msg = message_from_bytes(base64.urlsafe_b64decode(body["raw"] + "=="))
                text = msg.get_payload(decode=True).decode() if not msg.is_multipart() else ""
                mid = f"sent{len(self.sent_by_assistant) + 1}-{secrets.token_hex(3)}"
                to = [a.strip() for a in (msg["To"] or "").split(",") if a.strip()]
                self.add_email(mid, body.get("threadId") or mid, self.account, "", to, msg["Subject"] or "", text,
                               datetime.now(UTC), sent=True)
                self.sent_by_assistant.append({"to": to, "subject": msg["Subject"], "body": text,
                                               "at": datetime.now(UTC).isoformat()})
                return httpx.Response(200, json={"id": mid})
            if path == "/calendar/v3/calendars/primary/events" and method == "GET":
                return httpx.Response(200, json={"items": self.events})
            if path == "/calendar/v3/calendars/primary/events" and method == "POST":
                ev = json.loads(request.content)
                eid = f"new{len(self.created_events) + 1}"
                self.created_events.append(ev)
                self.events.append({**ev, "id": eid, "status": "confirmed"})
                return httpx.Response(200, json={"id": eid})
            if path == "/calendar/v3/freeBusy":
                busy = [{"start": e["start"]["dateTime"], "end": e["end"]["dateTime"]} for e in self.events
                        if "dateTime" in e.get("start", {})]
                return httpx.Response(200, json={"calendars": {"primary": {"busy": busy}}})
        return httpx.Response(404, json={"error": f"demo world has no {method} {path}"})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def inbox(self) -> list[dict]:
        out = []
        for m in self.messages.values():
            h = {x["name"]: x["value"] for x in m["payload"]["headers"]}
            out.append({"id": m["id"], "from": h.get("From", ""), "to": h.get("To", ""), "subject": h.get("Subject", ""),
                        "snippet": m["snippet"], "sent": "SENT" in m["labelIds"],
                        "newsletter": "List-Unsubscribe" in h,
                        "at": datetime.fromtimestamp(int(m["internalDate"]) / 1000, UTC).isoformat()})
        return sorted(out, key=lambda x: x["at"], reverse=True)

    def calendar(self) -> list[dict]:
        rows = [{"title": e.get("summary", ""), "start": e["start"].get("dateTime"), "end": e["end"].get("dateTime")}
                for e in self.events if "dateTime" in e.get("start", {})]
        return sorted(rows, key=lambda x: x["start"])


_worlds: dict[int, DemoWorld] = {}
_worlds_lock = threading.Lock()


def world_for(user_id: int, tz: str = "Asia/Kolkata") -> DemoWorld:
    with _worlds_lock:
        w = _worlds.get(user_id)
        if w is None:
            w = DemoWorld()
            seed_world(w, user_id, tz)
            _worlds[user_id] = w
        return w


def client_for(user_id: int, tz: str = "Asia/Kolkata") -> httpx.Client:
    return world_for(user_id, tz).client()


ME = DEMO_ACCOUNT
RAVI, PRIYA, ANIKA, RAHUL = "ravi@distrib.example", "priya@printhouse.example", "anika@pinevc.example", "rahul@fixit.example"


def seed_world(w: DemoWorld, uid: int, tz_name: str) -> None:
    """A realistic week for Sam, who runs a stationery business. Ids are stable per user so a restart
    re-creates the same mailbox and sync stays de-duplicated."""
    tz = zone(tz_name)
    now = datetime.now(tz)
    d = lambda days, hour, minute=0: (now - timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)  # noqa: E731
    p = f"d{uid}-"

    w.add_email(p + "m1", p + "t1", RAVI, "Ravi Menon", [ME], "GST invoice for the September consignment",
                "Hi Sam,\n\nCan you send the GST invoice for the September consignment? Our accountant needs it to "
                "file this week.\n\nThanks,\nRavi", d(3, 11, 5))
    w.add_email(p + "m2", p + "t1", ME, "Sam", [RAVI], "Re: GST invoice for the September consignment",
                "Sure Ravi, I'll send it over by Tuesday.\n\nSam", d(2, 18, 40), sent=True)

    w.add_email(p + "m3", p + "t2", ME, "Sam", [PRIYA], "Quote for 5,000 notebooks",
                "Hi Priya,\n\nCould you share a quote for 5,000 A5 ruled notebooks with our logo on the cover?\n\nSam",
                d(6, 10, 15), sent=True)
    w.add_email(p + "m4", p + "t2", PRIYA, "Priya Shah", [ME], "Re: Quote for 5,000 notebooks",
                "Hi Sam, thanks for checking. I'll send the revised quote by Friday.\n\nPriya", d(5, 9, 30))

    w.add_email(p + "m5", p + "t3", ANIKA, "Anika Rao", [ME], "Following up on our chat",
                "Hi Sam,\n\nGreat speaking yesterday. Before our call on Thursday, could you send me your repeat-order "
                "rate and the unit economics for the Pune store?\n\nBest,\nAnika\nPine Ventures", d(1, 16, 20))

    w.add_email(p + "m6", p + "t4", RAHUL, "Rahul (FixIt Homes)", [ME], "Plumber visit for your flat",
                "Hello Sam, the plumber can come this Saturday at 10am or 4pm. Which works for you?\n\nRahul", d(0, 8, 10))

    w.add_email(p + "m7", p + "t5", "billing@netflix.example", "Netflix", [ME], "Your membership has renewed",
                "Your Netflix Standard plan renewed today. Amount charged: INR 649. Next renewal next month.", d(4, 7))
    w.add_email(p + "m8", p + "t6", "receipts@cult.example", "Cult.fit", [ME], "Payment received: Cult Elite monthly",
                "We received INR 1,372 for your Cult Elite monthly membership. It renews automatically every month.", d(8, 6))
    w.add_email(p + "m9", p + "t7", "billing@workspace.example", "Google Workspace", [ME], "Your annual invoice",
                "Google Workspace Business Starter, annual plan: INR 8,280 charged. Renews yearly.", d(12, 9))
    w.add_email(p + "m10", p + "t8", "news@stationerydaily.example", "Stationery Daily", [ME], "This week in stationery",
                "Ten trends shaping the back-to-school season...", d(1, 7), newsletter=True)

    today = now.date()
    at = lambda day_offset, hour, minute=0: datetime.combine(today + timedelta(days=day_offset), time(hour, minute), tzinfo=tz)  # noqa: E731
    w.add_event(p + "e1", "Call with Anika (Pine Ventures)", at(0, 10, 30), 30, [ANIKA])
    w.add_event(p + "e2", "Lunch with Ravi", at(0, 13), 60, [RAVI])
    w.add_event(p + "e3", "Team stand-up", at(0, 16), 15)
    w.add_event(p + "e4", "Supplier visit, Waluj", at(1, 9), 90)
    w.add_event(p + "e5", "Investor call: Anika", at(3, 11), 45, [ANIKA])


SCENARIOS = [
    ("meera@springfield-school.example", "Meera Iyer", "Order: 200 registers by Friday",
     "Hi Sam,\n\nWe need 200 long-book registers delivered to the school by Friday. Can you send a quote today? "
     "If the price works we'll confirm tomorrow.\n\nMeera Iyer\nSpringfield School"),
    ("no-reply@indigo.example", "IndiGo", "Booking confirmed: BOM to BLR, Friday 07:10",
     "Your flight 6E 5321 from Mumbai (BOM) to Bengaluru (BLR) on Friday departs at 07:10. Reporting time 05:40. "
     "PNR X7K2QP."),
    (RAVI, "Ravi Menon", "Price change from next month",
     "Hi Sam,\n\nHeads up: Classmate long-book registers go up 8% from the 1st. If you want to lock the current "
     "price, place the order by Thursday.\n\nRavi"),
]


def inject_new_email(user_id: int, tz: str) -> dict:
    w = world_for(user_id, tz)
    frm, name, subject, body = SCENARIOS[w.next_scenario % len(SCENARIOS)]
    w.next_scenario += 1
    mid = f"d{user_id}-n{w.next_scenario}-{secrets.token_hex(2)}"
    w.add_email(mid, mid, frm, name, [ME], subject, body, datetime.now(UTC))
    return {"from": name, "from_addr": frm, "subject": subject}


# ------------------------------------------------------------------ demo accounts


def create_demo_user(session: Session, tz: str = "Asia/Kolkata", assistant_name: str = "Aide") -> User:
    try:
        zone(tz)
    except Exception:  # noqa: BLE001
        tz = "Asia/Kolkata"
    phone = "+000" + "".join(str(secrets.randbelow(10)) for _ in range(11))  # never a real, dialable number
    user = User(phone=phone, name="Sam", timezone=tz, onboarding_state="active", demo=True,
                assistant_name=assistant_name, last_inbound_at=utcnow(),
                persona="Warm, direct and brief.")
    session.add(user)
    session.flush()
    uid = user.id
    session.add(Connection(user_id=uid, provider="google", account_email=DEMO_ACCOUNT, scopes=DEMO_SCOPE,
                           access_token_enc=encrypt(uid, "demo"), refresh_token_enc=encrypt(uid, "demo"),
                           expires_at=utcnow() + timedelta(days=3650)))
    for email, name, note in [(RAVI, "Ravi Menon", "main register supplier"), (PRIYA, "Priya Shah", "printer"),
                              (ANIKA, "Anika Rao", "investor at Pine Ventures")]:
        session.add(Person(user_id=uid, email=email, name=name, relationship_note=note, importance=0.7,
                           messages_in=4, messages_out=4, last_contact_at=utcnow() - timedelta(days=2)))

    from app import standing, vault
    from app.context import memory

    for text in ["Runs Brightleaf Stationers, a stationery business in Aurangabad",
                 "Never schedule calls before 10am", "Prefers WhatsApp over email for anything urgent"]:
        memory.save(session, user, text, source="stated")
    session.add(Goal(user_id=uid, title="Open the Pune store", detail="Lease signed and first 500 products live",
                     target_date=(utcnow() + timedelta(days=70)).date(), progress_note="Two sites shortlisted"))
    session.add(Goal(user_id=uid, title="Close the seed round", target_date=(utcnow() + timedelta(days=55)).date(),
                     progress_note="Pine Ventures call on Thursday"))
    session.add(Goal(user_id=uid, title="Run 4 times a week", progress_note="3 runs last week"))
    standing.create(session, user, "Weekly cash review",
                    "Summarise money owed to me, money I owe and anything overdue, from email.", "weekly mon 09:00")
    standing.create(session, user, "Investor follow-ups",
                    "Find investor emails waiting on me for more than a day and draft replies.", "daily 18:30")
    vault.add(session, user, "Amazon", "amazon.in", "sam@brightleaf.example", secrets.token_urlsafe(12))
    world_for(uid, tz)
    return user


def delete_expired(session: Session) -> int:
    old = session.scalars(select(User).where(User.demo.is_(True), User.created_at < utcnow() - DEMO_TTL)).all()
    for u in old:
        _worlds.pop(u.id, None)
        session.delete(u)
    return len(old)


def forget_world(user_id: int) -> None:
    with _worlds_lock:
        _worlds.pop(user_id, None)


# ------------------------------------------------------------------ rate limits


_ip_hits: dict[str, deque] = defaultdict(deque)
_day_hits: deque = deque()
_rl_lock = threading.Lock()


def allow_new_demo(ip: str) -> bool:
    now = utcnow()
    with _rl_lock:
        q = _ip_hits[ip]
        while q and now - q[0] > timedelta(hours=1):
            q.popleft()
        while _day_hits and now - _day_hits[0] > timedelta(days=1):
            _day_hits.popleft()
        if len(q) >= MAX_DEMOS_PER_IP_PER_HOUR or len(_day_hits) >= MAX_DEMOS_PER_DAY:
            return False
        q.append(now)
        _day_hits.append(now)
        return True


def chat_allowed(session: Session, user: User, limit: int) -> bool:
    if not user.demo:
        return True
    n = session.query(Message).filter(Message.user_id == user.id, Message.direction == "in").count()
    return n < limit


# ------------------------------------------------------------------ background runs (status shown in the app)


_status: dict[int, dict] = {}
_runs: dict[int, int] = defaultdict(int)


def status(user_id: int) -> dict:
    return _status.get(user_id, {"busy": False, "stage": ""})


def _set(user_id: int, busy: bool, stage: str) -> None:
    _status[user_id] = {"busy": busy, "stage": stage}


def start_run(user_id: int, what: str) -> bool:
    """Kick off a background demo run. Returns False when one is already going or the demo is used up."""
    if status(user_id)["busy"] or _runs[user_id] >= MAX_RUNS_PER_DEMO:
        return False
    fn = RUNS.get(what)
    if fn is None:
        return False
    _runs[user_id] += 1
    _set(user_id, True, STAGE_LABELS.get(what, "Working"))
    threading.Thread(target=_run, args=(user_id, what, fn), daemon=True).start()
    return True


def _run(user_id: int, what: str, fn) -> None:
    try:
        fn(user_id)
    except Exception:  # noqa: BLE001 - a failed demo run must never take the server down
        log.exception("demo run %s failed for user %s", what, user_id)
        with session_scope() as s:
            user = s.get(User, user_id)
            if user:
                _say(s, user, "That demo step hit a snag on my side. Try it again in a moment.")
    finally:
        _set(user_id, False, "")


def _say(session: Session, user: User, text: str) -> None:
    from app.messenger import send

    send(session, user, text)


def _sync_and_extract(session: Session, user: User, llm) -> int:
    from app.context.extract import process_pending
    from app.integrations.sync import sync_user

    sync_user(session, user)
    return process_pending(session, user, llm)


def _fallback_loops(session: Session, user: User) -> None:
    """If the model is unavailable, seed the loops it would have found so the demo still makes sense."""
    if session.scalar(select(Commitment.id).where(Commitment.user_id == user.id).limit(1)):
        return
    people = {p.email: p for p in session.scalars(select(Person).where(Person.user_id == user.id)).all()}
    for direction, text, email, days in [("user_owes", "Send Ravi the GST invoice for September", RAVI, 1),
                                         ("owed_to_user", "Priya to send the notebook quote", PRIYA, -2),
                                         ("user_owes", "Send Anika repeat-order rate and Pune numbers", ANIKA, 2),
                                         ("user_owes", "Tell Rahul which plumber slot works", RAHUL, 0)]:
        session.add(Commitment(user_id=user.id, direction=direction, description=text,
                               person_id=people[email].id if email in people else None,
                               due_at=utcnow() + timedelta(days=days), confidence=0.9))


def run_welcome(user_id: int) -> None:
    from app import brief
    from app.llm import get_llm

    llm = get_llm()
    with session_scope() as s:
        user = s.get(User, user_id)
        _say(s, user, f"Hi Sam, I'm {user.assistant_name}. This is a live demo: I'm really thinking and acting, but "
                      "your inbox, calendar and the outside world are simulated, so nothing actually gets sent, booked "
                      "or paid.\n\nGive me a moment to read your inbox and calendar.")
    _set(user_id, True, "Reading the sample inbox and calendar")
    with session_scope() as s:
        user = s.get(User, user_id)
        try:
            _sync_and_extract(s, user, llm)
        except Exception:  # noqa: BLE001
            log.exception("demo extraction failed for user %s", user_id)
        _fallback_loops(s, user)
    _set(user_id, True, "Writing your morning brief")
    with session_scope() as s:
        user = s.get(User, user_id)
        _say(s, user, brief.compose(s, user, llm, greeting="Here's your brief for today, Sam."))
        brief.mark_sent(user)


def run_brief(user_id: int) -> None:
    from app import brief
    from app.llm import get_llm

    llm = get_llm()
    with session_scope() as s:
        user = s.get(User, user_id)
        _sync_and_extract(s, user, llm)
        _say(s, user, brief.compose(s, user, llm))


def run_new_email(user_id: int) -> None:
    from app.agent.agent import run_background
    from app.llm import get_llm
    from app.standing import NOTHING_NEW

    llm = get_llm()
    with session_scope() as s:
        user = s.get(User, user_id)
        info = inject_new_email(user_id, user.timezone)
    _set(user_id, True, f"New email from {info['from']}: reading it")
    with session_scope() as s:
        user = s.get(User, user_id)
        _sync_and_extract(s, user, llm)
        result = run_background(
            s, user,
            f"A new email just arrived from {info['from']} <{info['from_addr']}> with the subject \"{info['subject']}\". "
            "Read it. If it needs Sam, tell him in one or two lines what it is and prepare the right next step "
            "(a reply draft, a calendar hold or an errand) for his approval. If it needs nothing, reply NOTHING_NEW.",
            llm)
        if NOTHING_NEW not in result:
            _say(s, user, f"*New email from {info['from']}*\n{result}")
        else:
            _say(s, user, f"New email from {info['from']} (\"{info['subject']}\"). Nothing for you to do, I've filed it.")


def run_tasks(user_id: int) -> None:
    from app import standing
    from app.agent.agent import run_background
    from app.llm import get_llm
    from app.models import StandingTask

    llm = get_llm()
    with session_scope() as s:
        user = s.get(User, user_id)
        tasks = s.scalars(select(StandingTask).where(StandingTask.user_id == user_id, StandingTask.status == "active")).all()
        if not tasks:
            _say(s, user, "You don't have any standing tasks yet. Try: \"check every morning if Ravi has replied\".")
            return
        for t in tasks:
            t.next_run_at = utcnow() - timedelta(seconds=1)
    _set(user_id, True, "Running your standing tasks")
    with session_scope() as s:
        n = standing.run_due(s, lambda sess, u, task: run_background(sess, u, task.instruction, llm), limit=10)
        user = s.get(User, user_id)
        if n == 0:
            _say(s, user, "Ran your standing tasks. Nothing new to report.")


def run_ideas(user_id: int) -> None:
    from app import ideas
    from app.llm import get_llm

    llm = get_llm()
    with session_scope() as s:
        user = s.get(User, user_id)
        text = ideas.compose(s, user, llm)
        ideas.mark_sent(user)
        _say(s, user, text or "No new ideas tonight. Add a goal and I'll start suggesting next steps.")


RUNS = {"welcome": run_welcome, "brief": run_brief, "email": run_new_email, "tasks": run_tasks, "ideas": run_ideas}
STAGE_LABELS = {"welcome": "Setting up your demo", "brief": "Reading new mail and writing your brief",
                "email": "A new email is arriving", "tasks": "Running your standing tasks",
                "ideas": "Thinking about your goals"}


def simulated_result(action) -> str:
    """What a web task or phone call would have done, for demo accounts."""
    p = action.payload or {}
    goal = p.get("goal") or action.preview
    where = p.get("start_url") or "the web"
    return (f"Demo: in a real account I'd now open {where} in the secure browser and do this for you: {goal}. "
            "I'd stop and ask you before paying or sharing anything new. Nothing was booked in this demo.")


def purge_all_for_tests() -> None:
    with _worlds_lock:
        _worlds.clear()
    _status.clear()
    _runs.clear()
    with _rl_lock:
        _ip_hits.clear()
        _day_hits.clear()


def delete_demo_user(session: Session, user_id: int) -> None:
    forget_world(user_id)
    _status.pop(user_id, None)
    _runs.pop(user_id, None)
    user = session.get(User, user_id)
    if user and user.demo:
        session.delete(user)
        session.flush()
