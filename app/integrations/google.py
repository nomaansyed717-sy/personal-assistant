"""Google OAuth, Gmail and Calendar over plain REST.

Scopes requested (least privilege for V1):
- gmail.readonly   read mail to find commitments and answer questions
- gmail.send       send follow-ups the user approved
- calendar.events  read the calendar and create events the user approved

Note: gmail.readonly is a restricted scope. Up to 100 test users work while the
Google Cloud app is in "Testing"; a public launch needs Google's OAuth
verification and security assessment (see README).
"""
import base64
import html
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt, encrypt
from app.db import utcnow
from app.models import Connection, OAuthState
from app.util import aware

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CAL = "https://www.googleapis.com/calendar/v3"

SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
]

# Shared HTTP client; tests replace it with one backed by httpx.MockTransport.
_http: httpx.Client | None = None


def http() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client(timeout=30)
    return _http


def set_http(client: httpx.Client | None) -> None:
    global _http
    _http = client


class GoogleError(Exception):
    pass


# ---------------------------------------------------------------- OAuth


def redirect_uri() -> str:
    return get_settings().base_url.rstrip("/") + "/oauth/google/callback"


def start_url(session: Session, user_id: int) -> str:
    """A one-time link the assistant texts to the user."""
    token = secrets.token_urlsafe(24)
    session.add(OAuthState(token=token, user_id=user_id))
    return get_settings().base_url.rstrip("/") + f"/connect/google?s={token}"


def consent_url(state_token: str) -> str:
    s = get_settings()
    params = {
        "client_id": s.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state_token,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(session: Session, user_id: int, code: str) -> Connection:
    s = get_settings()
    resp = http().post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        },
    )
    if resp.status_code >= 400:
        raise GoogleError(f"token exchange failed: {resp.text[:300]}")
    tok = resp.json()
    info = http().get(USERINFO_URL, headers={"Authorization": f"Bearer {tok['access_token']}"}).json()

    conn = session.query(Connection).filter_by(user_id=user_id, provider="google").one_or_none()
    if conn is None:
        conn = Connection(user_id=user_id, provider="google")
        session.add(conn)
    conn.account_email = info.get("email")
    conn.scopes = tok.get("scope", "")
    conn.access_token_enc = encrypt(user_id, tok["access_token"])
    if tok.get("refresh_token"):
        conn.refresh_token_enc = encrypt(user_id, tok["refresh_token"])
    conn.expires_at = utcnow() + timedelta(seconds=int(tok.get("expires_in", 3600)))
    conn.status = "active"
    return conn


def revoke(conn: Connection) -> None:
    from app.demo import is_demo_connection

    if is_demo_connection(conn):
        return
    token = decrypt(conn.user_id, conn.refresh_token_enc or conn.access_token_enc)
    if token:
        try:
            http().post("https://oauth2.googleapis.com/revoke", params={"token": token})
        except httpx.HTTPError:
            log.warning("google revoke failed for user %s", conn.user_id)


# ---------------------------------------------------------------- authenticated client


class GoogleClient:
    def __init__(self, session: Session, conn: Connection):
        from app import demo

        self.session = session
        self.conn = conn
        self.demo = demo.is_demo_connection(conn)
        # Demo accounts talk to an in-memory mailbox and calendar; nothing reaches Google.
        self._http = demo.client_for(conn.user_id, conn.user.timezone if conn.user else "Asia/Kolkata") if self.demo else None

    def _token(self) -> str:
        c = self.conn
        if self.demo:
            return "demo"
        if c.expires_at and aware(c.expires_at) - utcnow() > timedelta(minutes=2):
            return decrypt(c.user_id, c.access_token_enc)
        refresh = decrypt(c.user_id, c.refresh_token_enc)
        if not refresh:
            c.status = "error"
            raise GoogleError("no refresh token; the user must reconnect Google")
        s = get_settings()
        resp = http().post(
            TOKEN_URL,
            data={
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code >= 400:
            c.status = "revoked" if "invalid_grant" in resp.text else "error"
            raise GoogleError(f"token refresh failed: {resp.text[:200]}")
        tok = resp.json()
        c.access_token_enc = encrypt(c.user_id, tok["access_token"])
        c.expires_at = utcnow() + timedelta(seconds=int(tok.get("expires_in", 3600)))
        return tok["access_token"]

    def _req(self, method: str, url: str, **kwargs) -> dict:
        headers = {"Authorization": f"Bearer {self._token()}"}
        resp = (self._http or http()).request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise GoogleError(f"{method} {url} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    # ---------------- Gmail

    def list_message_ids(self, query: str, max_results: int = 200) -> list[str]:
        ids, page = [], None
        while len(ids) < max_results:
            params = {"q": query, "maxResults": min(100, max_results - len(ids))}
            if page:
                params["pageToken"] = page
            data = self._req("GET", f"{GMAIL}/messages", params=params)
            ids += [m["id"] for m in data.get("messages", [])]
            page = data.get("nextPageToken")
            if not page:
                break
        return ids

    def get_message(self, msg_id: str) -> dict:
        return parse_gmail_message(self._req("GET", f"{GMAIL}/messages/{msg_id}", params={"format": "full"}))

    def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
        cc: list[str] | None = None,
    ) -> dict:
        msg = EmailMessage()
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        if self.conn.account_email:
            msg["From"] = self.conn.account_email
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id
        return self._req("POST", f"{GMAIL}/messages/send", json=payload)

    # ---------------- Calendar

    def list_events(self, start: datetime, end: datetime, max_results: int = 100) -> list[dict]:
        data = self._req(
            "GET",
            f"{CAL}/calendars/primary/events",
            params={
                "timeMin": start.astimezone(UTC).isoformat(),
                "timeMax": end.astimezone(UTC).isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": max_results,
            },
        )
        return [parse_calendar_event(e) for e in data.get("items", []) if e.get("status") != "cancelled"]

    def busy_blocks(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        data = self._req(
            "POST",
            f"{CAL}/freeBusy",
            json={
                "timeMin": start.astimezone(UTC).isoformat(),
                "timeMax": end.astimezone(UTC).isoformat(),
                "items": [{"id": "primary"}],
            },
        )
        blocks = data.get("calendars", {}).get("primary", {}).get("busy", [])
        return [(_parse_dt(b["start"]), _parse_dt(b["end"])) for b in blocks]

    def create_event(
        self, title: str, start: datetime, end: datetime, attendees: list[str] | None = None, description: str = ""
    ) -> dict:
        body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        if attendees:
            body["attendees"] = [{"email": a} for a in attendees]
        return self._req(
            "POST",
            f"{CAL}/calendars/primary/events",
            params={"sendUpdates": "all" if attendees else "none"},
            json=body,
        )


# ---------------------------------------------------------------- parsing helpers


def _parse_dt(value: str) -> datetime:
    if len(value) == 10:  # all-day "YYYY-MM-DD"
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", raw)
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", raw))).strip()


def _extract_body(part: dict) -> str:
    mime = part.get("mimeType", "")
    data = part.get("body", {}).get("data")
    if mime == "text/plain" and data:
        return _b64(data)
    plain, htm = "", ""
    for sub in part.get("parts", []) or []:
        text = _extract_body(sub)
        if not text:
            continue
        if sub.get("mimeType") == "text/html":
            htm = htm or text
        else:
            plain = plain or text
    if plain:
        return plain
    if htm:
        return htm
    if mime == "text/html" and data:
        return html_to_text(_b64(data))
    return ""


_QUOTE_MARKERS = re.compile(r"(?m)^(On .{5,120} wrote:|-{2,}\s*Original Message\s*-{2,}|From: .+\nSent: )")


def strip_quoted(text: str) -> str:
    """Drop quoted history so each email is judged on its own new content."""
    m = _QUOTE_MARKERS.search(text)
    if m:
        text = text[: m.start()]
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    return "\n".join(lines).strip()


def parse_gmail_message(msg: dict) -> dict:
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    from_name, from_addr = parseaddr(headers.get("from", ""))
    to = [a for _, a in getaddresses([headers.get("to", ""), headers.get("cc", "")]) if a]
    try:
        when = parsedate_to_datetime(headers["date"]) if headers.get("date") else None
    except (TypeError, ValueError):
        when = None
    if when is None or when.tzinfo is None:
        when = datetime.fromtimestamp(int(msg.get("internalDate", "0")) / 1000, tz=UTC)
    body = _extract_body(msg.get("payload", {}))
    if "<html" in body[:200].lower() or "<div" in body[:200].lower():
        body = html_to_text(body)
    labels = msg.get("labelIds", [])
    return {
        "id": msg["id"],
        "thread_id": msg.get("threadId"),
        "from_name": from_name or None,
        "from_addr": (from_addr or "").lower() or None,
        "to": [a.lower() for a in to],
        "subject": headers.get("subject", ""),
        "date": when,
        "body": strip_quoted(body)[:6000],
        "snippet": html.unescape(msg.get("snippet", "")),
        "sent": "SENT" in labels,
        "message_id_header": headers.get("message-id"),
        "list_unsubscribe": bool(headers.get("list-unsubscribe")),
        "labels": labels,
    }


def parse_calendar_event(e: dict) -> dict:
    start = e.get("start", {})
    end = e.get("end", {})
    return {
        "id": e["id"],
        "title": e.get("summary", "(no title)"),
        "start": _parse_dt(start.get("dateTime") or start.get("date")),
        "end": _parse_dt(end.get("dateTime") or end.get("date")) if end else None,
        "all_day": "date" in start,
        "attendees": [a.get("email", "").lower() for a in e.get("attendees", []) if a.get("email")],
        "location": e.get("location"),
        "description": (e.get("description") or "")[:1000],
        "html_link": e.get("htmlLink"),
    }
