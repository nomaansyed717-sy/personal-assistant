"""Connected apps: any service that speaks MCP (the Model Context Protocol) becomes a set of tools.

A connector is a remote MCP server reached over Streamable HTTP: Notion, Linear, GitHub, Stripe, or a
Zapier / Composio URL that fronts thousands of apps. Three ways to authenticate:

  none   the URL itself carries the secret (Zapier, Composio)
  token  a bearer token or API key the user pastes once (GitHub PAT, Stripe restricted key)
  oauth  MCP's standard OAuth: discovery, dynamic client registration, PKCE (Notion, Linear)

Safety: tools the server marks read-only run straight away and their output reaches the model as untrusted
data. Every other tool call becomes an "app_action" proposal that waits for the user's yes (tier 2, tier 3
when the server marks it destructive), and Sentinel reviews it before it runs.
"""
import base64
import hashlib
import json
import logging
import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode, urljoin, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt, encrypt
from app.db import utcnow
from app.models import Connector, OAuthState, User
from app.util import aware

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
TIMEOUT = 30
MAX_TOOLS = 200
# Tests swap in an httpx.MockTransport here.
_transport: httpx.BaseTransport | None = None

# Popular remote MCP servers. "auth" says how the user signs in; "help" tells them where to get a token or URL.
CATALOG = [
    {"id": "zapier", "name": "Zapier (8,000+ apps)", "auth": "none", "url": "",
     "help": "Create a server at mcp.zapier.com, add the actions you want, and paste its server URL.",
     "blurb": "Gmail, Sheets, WhatsApp Business, Shopify, HubSpot and thousands more through one link."},
    {"id": "notion", "name": "Notion", "auth": "oauth", "url": "https://mcp.notion.com/mcp",
     "help": "", "blurb": "Search, read and update your pages and databases."},
    {"id": "linear", "name": "Linear", "auth": "oauth", "url": "https://mcp.linear.app/mcp",
     "help": "", "blurb": "Create and update issues, check what's assigned to you."},
    {"id": "github", "name": "GitHub", "auth": "token", "url": "https://api.githubcopilot.com/mcp/",
     "help": "Create a fine-grained personal access token at github.com/settings/tokens and paste it.",
     "blurb": "Issues, pull requests, repositories and code search."},
    {"id": "stripe", "name": "Stripe", "auth": "token", "url": "https://mcp.stripe.com",
     "help": "Create a restricted API key in the Stripe dashboard (Developers > API keys) and paste it.",
     "blurb": "Payments, customers, invoices and refunds (refunds always need your yes)."},
    {"id": "composio", "name": "Composio (250+ apps)", "auth": "none", "url": "",
     "help": "Create an MCP server at composio.dev and paste its URL.",
     "blurb": "Slack, Jira, Salesforce, Calendly and more through one link."},
    {"id": "custom", "name": "Any MCP server", "auth": "token", "url": "",
     "help": "Paste the server's URL, and a token if it needs one.", "blurb": "Connect anything that speaks MCP."},
]


class ConnectorError(Exception):
    pass


class NeedsAuth(ConnectorError):
    """The server wants (fresh) credentials."""


def catalog_entry(catalog_id: str) -> dict | None:
    return next((c for c in CATALOG if c["id"] == catalog_id), None)


def make_slug(session: Session, user_id: int, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:20] or "app"
    slug, n = base, 2
    while session.scalar(select(Connector).where(Connector.user_id == user_id, Connector.slug == slug)):
        slug, n = f"{base}_{n}", n + 1
    return slug


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=True)


def _check_url(url: str) -> None:
    """Only public https servers (Sentinel's SSRF rules), except plain http on localhost in development."""
    from app.sentinel import check_url

    p = urlparse(url)
    if p.scheme not in ("https", "http") or not p.netloc:
        raise ConnectorError("That doesn't look like a server URL.")
    if p.scheme == "http" and get_settings().env == "prod":
        raise ConnectorError("The server must use https.")
    if _transport is None and get_settings().env == "prod":
        v = check_url(url)
        if not v.allowed:
            raise ConnectorError(f"That address isn't allowed: {v.reason}")


# ------------------------------------------------------------------ MCP over Streamable HTTP


class MCPSession:
    """One short-lived MCP session: initialize, then requests. The server may answer with JSON or an SSE stream."""

    def __init__(self, url: str, token: str | None = None):
        self.url = url
        self.token = token
        self.session_id: str | None = None
        self._id = 0
        self.http = _client()

    def __enter__(self):
        self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                    "clientInfo": {"name": get_settings().app_name, "version": "1.0"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)
        return self

    def __exit__(self, *exc):
        if self.session_id:
            try:
                self.http.delete(self.url, headers=self._headers())
            except httpx.HTTPError:
                pass
        self.http.close()

    def _headers(self) -> dict:
        h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
             "MCP-Protocol-Version": PROTOCOL_VERSION}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _post(self, body: dict, expect_reply: bool = True) -> dict | None:
        try:
            r = self.http.post(self.url, headers=self._headers(), content=json.dumps(body))
        except httpx.HTTPError as exc:
            raise ConnectorError(f"couldn't reach the server ({str(exc)[:120]})") from exc
        if r.status_code in (401, 403):
            raise NeedsAuth(r.headers.get("www-authenticate", ""))
        if r.status_code >= 400:
            raise ConnectorError(f"server error {r.status_code}: {r.text[:200]}")
        if sid := r.headers.get("mcp-session-id"):
            self.session_id = sid
        if not expect_reply:
            return None
        ctype = r.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            for msg in _sse_messages(r.text):
                if msg.get("id") == body.get("id"):
                    return msg
            raise ConnectorError("the server sent no reply")
        try:
            data = r.json()
        except ValueError as exc:
            raise ConnectorError("the server's reply wasn't JSON") from exc
        if isinstance(data, list):  # a batch: pick ours
            data = next((m for m in data if m.get("id") == body.get("id")), {})
        return data

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        if not msg:
            raise ConnectorError("empty reply")
        if "error" in msg:
            raise ConnectorError(str(msg["error"].get("message", msg["error"]))[:300])
        return msg.get("result") or {}

    def list_tools(self) -> list[dict]:
        tools, cursor = [], None
        while len(tools) < MAX_TOOLS:
            res = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools += res.get("tools", [])
            cursor = res.get("nextCursor")
            if not cursor:
                break
        return tools[:MAX_TOOLS]

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})


def _sse_messages(text: str) -> list[dict]:
    out, data = [], []
    for line in text.splitlines() + [""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line.strip() and data:
            try:
                out.append(json.loads("\n".join(data)))
            except ValueError:
                pass
            data = []
    return out


def result_text(result: dict, limit: int = 6000) -> str:
    """Flatten an MCP tool result into text."""
    parts = []
    for c in result.get("content", []) or []:
        if c.get("type") == "text":
            parts.append(c.get("text", ""))
        elif c.get("type") == "resource" and isinstance(c.get("resource"), dict):
            parts.append(c["resource"].get("text") or c["resource"].get("uri", ""))
        else:
            parts.append(f"[{c.get('type', 'content')}]")
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"])[:limit])
    return ("\n".join(parts) or "(no output)")[:limit]


# ------------------------------------------------------------------ tokens


def _token(session: Session, c: Connector) -> str | None:
    if c.auth == "none":
        return None
    if c.auth == "oauth" and c.expires_at and aware(c.expires_at) < utcnow() + timedelta(seconds=60):
        _refresh(session, c)
    return decrypt(c.user_id, c.token_enc)


def _refresh(session: Session, c: Connector) -> None:
    meta = c.oauth_meta or {}
    refresh = decrypt(c.user_id, c.refresh_token_enc)
    if not refresh or not meta.get("token_endpoint"):
        c.status = "needs_auth"
        raise NeedsAuth("sign in again")
    data = {"grant_type": "refresh_token", "refresh_token": refresh, "client_id": meta.get("client_id", ""),
            "resource": c.url}
    if meta.get("client_secret_enc"):
        data["client_secret"] = decrypt(c.user_id, meta["client_secret_enc"])
    with _client() as http:
        r = http.post(meta["token_endpoint"], data=data, headers={"Accept": "application/json"})
    if r.status_code >= 400:
        c.status = "needs_auth"
        raise NeedsAuth("sign in again")
    _store_tokens(c, r.json())


def _store_tokens(c: Connector, tok: dict) -> None:
    c.token_enc = encrypt(c.user_id, tok["access_token"])
    if tok.get("refresh_token"):
        c.refresh_token_enc = encrypt(c.user_id, tok["refresh_token"])
    c.expires_at = utcnow() + timedelta(seconds=int(tok.get("expires_in") or 3600))
    c.status = "active"


# ------------------------------------------------------------------ OAuth (MCP authorization spec)


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _discover(url: str, www_authenticate: str = "") -> dict:
    """Protected resource metadata -> authorization server metadata."""
    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    m = re.search(r'resource_metadata="([^"]+)"', www_authenticate or "")
    candidates = [m.group(1)] if m else []
    candidates += [f"{origin}/.well-known/oauth-protected-resource{p.path.rstrip('/')}",
                   f"{origin}/.well-known/oauth-protected-resource"]
    auth_server = origin
    with _client() as http:
        for u in candidates:
            try:
                r = http.get(u)
            except httpx.HTTPError:
                continue
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                servers = r.json().get("authorization_servers") or []
                if servers:
                    auth_server = servers[0].rstrip("/")
                    break
        ap = urlparse(auth_server)
        a_origin, a_path = f"{ap.scheme}://{ap.netloc}", ap.path.rstrip("/")
        for u in (f"{a_origin}/.well-known/oauth-authorization-server{a_path}",
                  f"{a_origin}/.well-known/openid-configuration{a_path}",
                  f"{auth_server}/.well-known/openid-configuration"):
            try:
                r = http.get(u)
            except httpx.HTTPError:
                continue
            if r.status_code == 200:
                meta = r.json()
                if meta.get("authorization_endpoint") and meta.get("token_endpoint"):
                    return meta
    # Last resort: the spec's default endpoints on the server's origin.
    return {"authorization_endpoint": urljoin(origin, "/authorize"), "token_endpoint": urljoin(origin, "/token"),
            "registration_endpoint": urljoin(origin, "/register")}


def redirect_uri() -> str:
    return get_settings().base_url.rstrip("/") + "/oauth/connector/callback"


def start_oauth(session: Session, user: User, c: Connector, return_to: str = "app", www_authenticate: str = "") -> str:
    """Register Aide with the server (if needed) and return the URL the user opens to sign in."""
    meta = _discover(c.url, www_authenticate)
    stored = dict(c.oauth_meta or {})
    if not stored.get("client_id") or stored.get("registered_redirect") != redirect_uri():
        if not meta.get("registration_endpoint"):
            raise ConnectorError("This server doesn't let new apps register. Use a token instead.")
        with _client() as http:
            r = http.post(meta["registration_endpoint"], json={
                "client_name": get_settings().app_name, "redirect_uris": [redirect_uri()],
                "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
                "token_endpoint_auth_method": "none"})
        if r.status_code >= 400:
            raise ConnectorError(f"couldn't register with the server ({r.status_code})")
        reg = r.json()
        stored["client_id"] = reg["client_id"]
        if reg.get("client_secret"):
            stored["client_secret_enc"] = encrypt(user.id, reg["client_secret"])
        stored["registered_redirect"] = redirect_uri()
    stored["token_endpoint"] = meta["token_endpoint"]
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(32)
    stored["pkce_enc"] = encrypt(user.id, verifier)
    stored["state"] = state
    c.oauth_meta = stored
    c.status = "needs_auth"
    session.add(OAuthState(token=state, user_id=user.id, return_to=return_to))
    params = {"response_type": "code", "client_id": stored["client_id"], "redirect_uri": redirect_uri(),
              "code_challenge": challenge, "code_challenge_method": "S256", "state": state, "resource": c.url}
    if meta.get("scopes_supported"):
        params["scope"] = " ".join(meta["scopes_supported"])
    return meta["authorization_endpoint"] + ("&" if "?" in meta["authorization_endpoint"] else "?") + urlencode(params)


def finish_oauth(session: Session, state: str, code: str) -> tuple[Connector, str]:
    st = session.scalar(select(OAuthState).where(OAuthState.token == state))
    if not st or st.used or utcnow() - aware(st.created_at) > timedelta(hours=1):
        raise ConnectorError("This sign-in link has expired. Try connecting again.")
    st.used = True
    c = next((x for x in session.scalars(select(Connector).where(Connector.user_id == st.user_id)).all()
              if (x.oauth_meta or {}).get("state") == state), None)
    if c is None:
        raise ConnectorError("That connection no longer exists.")
    meta = c.oauth_meta or {}
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
            "client_id": meta["client_id"], "code_verifier": decrypt(c.user_id, meta["pkce_enc"]), "resource": c.url}
    if meta.get("client_secret_enc"):
        data["client_secret"] = decrypt(c.user_id, meta["client_secret_enc"])
    with _client() as http:
        r = http.post(meta["token_endpoint"], data=data, headers={"Accept": "application/json"})
    if r.status_code >= 400:
        raise ConnectorError(f"the server didn't accept the sign-in ({r.status_code})")
    _store_tokens(c, r.json())
    c.oauth_meta = {k: v for k, v in meta.items() if k not in ("pkce_enc", "state")}
    refresh_tools(session, c)
    return c, st.return_to or "app"


# ------------------------------------------------------------------ tools


def refresh_tools(session: Session, c: Connector) -> list[dict]:
    """Fetch and cache the server's tool list."""
    try:
        with MCPSession(c.url, _token(session, c)) as s:
            raw = s.list_tools()
    except NeedsAuth:
        c.status = "needs_auth"
        raise
    except ConnectorError as exc:
        c.status = "error"
        c.last_error = str(exc)[:300]
        raise
    c.tools = [{
        "name": t["name"],
        "description": (t.get("description") or "")[:400],
        "input_schema": t.get("inputSchema") or {"type": "object", "properties": {}},
        "read_only": bool((t.get("annotations") or {}).get("readOnlyHint")),
        "destructive": bool((t.get("annotations") or {}).get("destructiveHint")),
    } for t in raw]
    c.status, c.last_error, c.tools_at = "active", None, utcnow()
    return c.tools


def call(session: Session, c: Connector, tool: str, arguments: dict) -> str:
    try:
        with MCPSession(c.url, _token(session, c)) as s:
            res = s.call_tool(tool, arguments)
    except NeedsAuth:
        c.status = "needs_auth"
        raise ConnectorError(f"{c.name} needs you to sign in again (More > Connected apps)") from None
    text = result_text(res)
    if res.get("isError"):
        raise ConnectorError(text[:300])
    return text


def find(session: Session, user_id: int, app: str) -> Connector | None:
    app = (app or "").strip().lower()
    rows = session.scalars(select(Connector).where(Connector.user_id == user_id)).all()
    return next((c for c in rows if c.slug == app), None) or next((c for c in rows if c.name.lower() == app), None)


def tool_info(c: Connector, tool: str) -> dict | None:
    return next((t for t in (c.tools or []) if t["name"] == tool), None)


def prompt_block(session: Session, user: User) -> str:
    rows = session.scalars(select(Connector).where(Connector.user_id == user.id, Connector.status == "active")).all()
    if not rows:
        return "- none (the user can connect apps under More > Connected apps)"
    return "\n".join(f"- {c.slug}: {c.name} ({len(c.tools or [])} tools)" for c in rows)


def public(c: Connector) -> dict:
    return {"id": c.id, "name": c.name, "slug": c.slug, "catalog_id": c.catalog_id, "auth": c.auth,
            "status": c.status, "last_error": c.last_error, "url_host": urlparse(c.url).netloc,
            "tools": [{"name": t["name"], "read_only": t["read_only"]} for t in (c.tools or [])][:60],
            "tool_count": len(c.tools or [])}
