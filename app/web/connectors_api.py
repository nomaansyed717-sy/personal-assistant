"""API for connected apps (MCP servers): browse the catalog, connect, sign in, refresh, remove."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import connectors
from app.audit import audit
from app.crypto import encrypt
from app.db import session_scope
from app.models import Connector, User
from app.web.api import current_user_id

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/connectors")
MAX_CONNECTORS = 20


def _own(s, uid: int, cid: int) -> Connector:
    c = s.get(Connector, cid)
    if not c or c.user_id != uid:
        raise HTTPException(status_code=404, detail="no such app")
    return c


@router.get("/catalog")
def catalog():
    return connectors.CATALOG


@router.get("")
def list_connectors(uid: int = Depends(current_user_id)):
    with session_scope() as s:
        rows = s.scalars(select(Connector).where(Connector.user_id == uid).order_by(Connector.created_at)).all()
        return [connectors.public(c) for c in rows]


class ConnectIn(BaseModel):
    catalog_id: str = Field(max_length=32)
    url: str | None = Field(default=None, max_length=1000)
    token: str | None = Field(default=None, max_length=4000)
    name: str | None = Field(default=None, max_length=80)
    client: str = Field(default="app", pattern="^(app|web)$")


@router.post("")
def connect(body: ConnectIn, uid: int = Depends(current_user_id)):
    entry = connectors.catalog_entry(body.catalog_id)
    if entry is None:
        raise HTTPException(status_code=400, detail="unknown app")
    url = (body.url or entry["url"] or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Paste the server URL")
    auth = entry["auth"]
    token = (body.token or "").strip() or None
    if body.catalog_id == "custom":
        auth = "token" if token else "none"
    if auth == "token" and not token:
        raise HTTPException(status_code=400, detail="Paste the token")
    try:
        connectors._check_url(url)
    except connectors.ConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with session_scope() as s:
        user = s.get(User, uid)
        if user.demo:
            raise HTTPException(status_code=403, detail="Connected apps need your own account, not the demo")
        if len(s.scalars(select(Connector).where(Connector.user_id == uid)).all()) >= MAX_CONNECTORS:
            raise HTTPException(status_code=400, detail=f"You can connect up to {MAX_CONNECTORS} apps")
        name = (body.name or entry["name"].split(" (")[0]).strip()
        c = Connector(user_id=uid, name=name, slug=connectors.make_slug(s, uid, name), catalog_id=body.catalog_id,
                      url_enc=encrypt(uid, url), auth=auth, token_enc=encrypt(uid, token) if token else None,
                      oauth_meta={}, tools=[])
        s.add(c)
        s.flush()
        audit(s, uid, "app_connected", name, actor="user")
        auth_url = None
        try:
            if auth == "oauth":
                auth_url = connectors.start_oauth(s, user, c, body.client)
            else:
                connectors.refresh_tools(s, c)
        except connectors.NeedsAuth as exc:
            if auth == "none":
                # The server wants OAuth after all (a plain URL that isn't pre-authorised).
                c.auth = "oauth"
                auth_url = connectors.start_oauth(s, user, c, body.client, str(exc))
            else:
                s.delete(c)
                raise HTTPException(status_code=400, detail="The server didn't accept that token") from exc
        except connectors.ConnectorError as exc:
            s.delete(c)
            raise HTTPException(status_code=400, detail=f"Couldn't connect: {exc}") from exc
        return {"connector": connectors.public(c), "auth_url": auth_url}


@router.post("/{cid}/signin")
def signin(cid: int, client: str = "app", uid: int = Depends(current_user_id)):
    with session_scope() as s:
        c = _own(s, uid, cid)
        if c.auth != "oauth":
            raise HTTPException(status_code=400, detail="This app uses a token; remove it and connect again")
        try:
            return {"auth_url": connectors.start_oauth(s, s.get(User, uid), c, client if client in ("app", "web") else "app")}
        except connectors.ConnectorError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{cid}/refresh")
def refresh(cid: int, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        c = _own(s, uid, cid)
        try:
            connectors.refresh_tools(s, c)
        except connectors.NeedsAuth:
            pass
        except connectors.ConnectorError:
            pass
        return connectors.public(c)


@router.delete("/{cid}")
def remove(cid: int, uid: int = Depends(current_user_id)):
    with session_scope() as s:
        c = _own(s, uid, cid)
        audit(s, uid, "app_disconnected", c.name, actor="user")
        s.delete(c)
    return {"ok": True}
