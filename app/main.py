"""HTTP surface: WhatsApp webhook, Google OAuth, privacy page, health, and a dev simulator."""
import logging
import threading
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import timedelta
from html import escape

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.agent import onboarding
from app.agent.router import handle_inbound
from app.channels import ConsoleChannel, InboundMessage, get_channel
from app.channels.whatsapp import parse_webhook, verify_signature
from app.config import get_settings, missing_config
from app.db import init_db, session_scope, utcnow
from app.integrations import google
from app.llm import get_llm
from app.models import OAuthState, User
from app.util import aware, normalize_phone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    missing = missing_config()
    if missing:
        if get_settings().env == "prod":
            raise RuntimeError(f"missing required settings: {', '.join(missing)}")
        log.warning("missing settings (fine for local dev): %s", ", ".join(missing))
    init_db()
    yield


app = FastAPI(title="Assistant", docs_url=None, redoc_url=None, lifespan=lifespan)

# One message at a time per user, so approvals and replies never interleave.
_user_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


# ------------------------------------------------------------------ WhatsApp


@app.get("/webhooks/whatsapp")
def whatsapp_verify(request: Request):
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == get_settings().whatsapp_verify_token:
        return PlainTextResponse(p.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="verification failed")


@app.post("/webhooks/whatsapp")
async def whatsapp_inbound(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("x-hub-signature-256"), get_settings().whatsapp_app_secret):
        raise HTTPException(status_code=401, detail="bad signature")
    for msg in parse_webhook(await request.json()):
        background.add_task(process_message, msg)
    return {"ok": True}  # Meta retries anything that isn't a fast 200


def process_message(msg: InboundMessage, channel_name: str = "whatsapp") -> None:
    with _user_locks[msg.phone]:
        try:
            with session_scope() as session:
                handle_inbound(session, msg, get_llm(), channel_name)
        except Exception:  # noqa: BLE001
            log.exception("failed handling message from %s", msg.phone[-4:])
            try:
                get_channel().send_text(msg.phone, "Sorry, something went wrong on my side. Please try that again.")
            except Exception:  # noqa: BLE001
                log.exception("could not send error notice")


# ------------------------------------------------------------------ Google OAuth


@app.get("/connect/google")
def connect_google(s: str):
    with session_scope() as session:
        state = session.scalar(select(OAuthState).where(OAuthState.token == s))
        if not state or state.used or utcnow() - aware(state.created_at) > timedelta(hours=24):
            return HTMLResponse(_page("This link has expired", "Send any message to your assistant on WhatsApp to get a new one."), 400)
    return RedirectResponse(google.consent_url(s))


@app.get("/oauth/google/callback")
def google_callback(background: BackgroundTasks, state: str = "", code: str = "", error: str = ""):
    if error:
        return HTMLResponse(_page("Not connected", "Google access wasn't granted. You can try again from WhatsApp."), 400)
    with session_scope() as session:
        st = session.scalar(select(OAuthState).where(OAuthState.token == state))
        if not st or st.used:
            return HTMLResponse(_page("This link has expired", "Ask your assistant for a new link."), 400)
        st.used = True
        user_id = st.user_id
        google.exchange_code(session, user_id, code)
    background.add_task(_after_connect, user_id)
    return HTMLResponse(_page("You're connected", "Head back to WhatsApp. I'll text you what I find in a few minutes."))


def _after_connect(user_id: int) -> None:
    try:
        with session_scope() as session:
            user = session.get(User, user_id)
            if user:
                onboarding.after_connect(session, user, get_llm())
    except Exception:  # noqa: BLE001
        log.exception("after_connect failed for user %s", user_id)


# ------------------------------------------------------------------ pages


def _page(title: str, body: str) -> str:
    name = escape(get_settings().app_name)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} · {name}</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;max-width:640px;margin:48px auto;padding:0 16px;color:#1d1d1f}}
h1{{font-size:24px}} h2{{font-size:18px;margin-top:28px}}</style></head>
<body><h1>{escape(title)}</h1>{body if body.startswith('<') else f'<p>{escape(body)}</p>'}</body></html>"""


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    s = get_settings()
    body = f"""
<p>{escape(s.app_name)} is a personal assistant you reach over WhatsApp. This page explains what it does with your data.</p>
<h2>What we access</h2><p>With your permission: your Gmail (read, and send only messages you approve) and Google Calendar
(read, and create events you approve). Your WhatsApp messages to the assistant. We do not read your other WhatsApp chats.</p>
<h2>What we keep</h2><p>Raw email and calendar text is encrypted with a key unique to you and deleted after
{s.raw_retention_days} days. We keep structured notes: people you deal with, open commitments, and preferences you state.
You can see them any time ("what do you know") and delete them ("forget &lt;name&gt;", "delete everything").</p>
<h2>What we never do</h2><p>Sell your data. Send anything to someone new without your explicit yes. Handle passwords,
card numbers or payments. Use your data to train models unless you opt in.</p>
<h2>Who processes it</h2><p>Hosting provider, Meta (WhatsApp delivery), Google (your account), Anthropic (Claude, the AI model,
under API terms that do not use your data for training).</p>
<h2>Your rights</h2><p>Access, correction, deletion and withdrawal of consent, from chat or by writing to the operator.
These apply under GDPR, CCPA/CPRA, India's DPDP Act and similar laws.</p>"""
    return _page("Privacy and terms", body)


# ------------------------------------------------------------------ development simulator


class SimIn(BaseModel):
    phone: str
    text: str
    name: str | None = None


@app.post("/dev/simulate")
def simulate(m: SimIn):
    """Talk to the assistant without WhatsApp (dev only). Returns what it would have sent."""
    if get_settings().env == "prod":
        raise HTTPException(status_code=404)
    ch = get_channel()
    if not isinstance(ch, ConsoleChannel):
        raise HTTPException(status_code=400, detail="simulator needs the console channel (unset WHATSAPP_TOKEN)")
    before = len(ch.sent)
    phone = normalize_phone(m.phone)
    process_message(
        InboundMessage(phone=phone, text=m.text, external_id=f"sim-{utcnow().timestamp()}", profile_name=m.name),
        channel_name="console",
    )
    return {"replies": [t for p, t in ch.sent[before:] if p == phone]}
