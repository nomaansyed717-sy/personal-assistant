"""Credential vault. Values are encrypted per user and only ever decrypted inside the browser
executor, at the moment it types them into a login form. The model sees labels and sites only."""
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.crypto import decrypt, encrypt
from app.models import User, VaultItem


def _domain(site: str) -> str:
    site = site.strip().lower()
    if "://" in site:
        site = urlparse(site).hostname or site
    return site.removeprefix("www.").strip("/")


def add(session: Session, user: User, label: str, site: str, username: str, secret: str) -> VaultItem:
    item = VaultItem(user_id=user.id, label=label.strip()[:120], site=_domain(site),
                     username_enc=encrypt(user.id, username), secret_enc=encrypt(user.id, secret))
    session.add(item)
    session.flush()
    audit(session, user.id, "vault_added", f"{item.label} ({item.site})", actor="user")
    return item


def listing(session: Session, user: User) -> list[dict]:
    rows = session.scalars(select(VaultItem).where(VaultItem.user_id == user.id).order_by(VaultItem.label)).all()
    return [{"id": v.id, "label": v.label, "site": v.site} for v in rows]


def remove(session: Session, user: User, item_id: int) -> bool:
    v = session.get(VaultItem, item_id)
    if v and v.user_id == user.id:
        audit(session, user.id, "vault_removed", f"{v.label} ({v.site})", actor="user")
        session.delete(v)
        return True
    return False


def credentials_for(session: Session, user: User, url_or_label: str) -> tuple[str, str] | None:
    """Executor-only. Matches by label, or by the domain of the page being filled."""
    key = url_or_label.strip().lower()
    host = _domain(key)
    for v in session.scalars(select(VaultItem).where(VaultItem.user_id == user.id)).all():
        if v.label.lower() == key or host == v.site or host.endswith("." + v.site):
            return decrypt(user.id, v.username_enc), decrypt(user.id, v.secret_enc)
    return None
