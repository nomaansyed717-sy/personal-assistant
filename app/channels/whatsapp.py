"""WhatsApp Business Platform (Cloud API) adapter.

Docs: https://developers.facebook.com/docs/whatsapp/cloud-api
- Inbound messages arrive at POST /webhooks/whatsapp, signed with the app secret.
- Free-form messages can only be sent within 24 hours of the user's last message.
  Outside that window we send an approved template (WHATSAPP_REOPEN_TEMPLATE),
  and deliver the queued content once the user replies.
"""
import hashlib
import hmac
import logging

import httpx

from app.channels.base import Channel, InboundMessage
from app.config import get_settings
from app.util import normalize_phone

log = logging.getLogger(__name__)


def verify_signature(raw_body: bytes, header: str | None, app_secret: str) -> bool:
    if not app_secret:
        # Allowed only in development; production must set WHATSAPP_APP_SECRET.
        return get_settings().env != "prod"
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def parse_webhook(payload: dict) -> list[InboundMessage]:
    """Extract user messages from a webhook payload. Delivery statuses are ignored."""
    out: list[InboundMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                sender = m.get("from", "")
                mtype = m.get("type")
                text, kind = "", "text"
                media_id = mime = filename = None
                if mtype in ("image", "document", "audio", "voice", "video", "sticker"):
                    media = m.get(mtype, {})
                    media_id, mime = media.get("id"), media.get("mime_type")
                    filename = media.get("filename")
                    text = media.get("caption", "") or ""
                    kind = {"voice": "audio", "video": "unsupported", "sticker": "unsupported"}.get(mtype, mtype)
                elif mtype == "text":
                    text = m.get("text", {}).get("body", "")
                elif mtype == "button":
                    text, kind = m.get("button", {}).get("text", ""), "button"
                elif mtype == "interactive":
                    inter = m.get("interactive", {})
                    reply = inter.get("button_reply") or inter.get("list_reply") or {}
                    text, kind = reply.get("title", ""), "button"
                elif mtype not in ("image", "document", "audio", "voice", "video", "sticker"):
                    kind = "unsupported"
                out.append(
                    InboundMessage(
                        phone=normalize_phone(sender),
                        text=text.strip(),
                        external_id=m.get("id", ""),
                        profile_name=names.get(sender),
                        kind=kind,
                        raw=m,
                        media_id=media_id,
                        mime=mime,
                        filename=filename,
                    )
                )
    return out


class WhatsAppChannel(Channel):
    name = "whatsapp"
    max_len = 4000
    has_session_window = True

    def __init__(self, client: httpx.Client | None = None):
        s = get_settings()
        self.url = f"https://graph.facebook.com/{s.whatsapp_api_version}/{s.whatsapp_phone_number_id}/messages"
        self.token = s.whatsapp_token
        self.language = s.whatsapp_template_language
        self.client = client or httpx.Client(timeout=20)

    def _post(self, body: dict) -> str | None:
        resp = self.client.post(self.url, json=body, headers={"Authorization": f"Bearer {self.token}"})
        if resp.status_code >= 400:
            log.error("whatsapp send failed %s: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
        data = resp.json()
        msgs = data.get("messages") or [{}]
        return msgs[0].get("id")

    def send_text(self, phone: str, text: str) -> str | None:
        return self._post(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": phone.lstrip("+"),
                "type": "text",
                "text": {"body": text, "preview_url": False},
            }
        )

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        base = self.url.rsplit("/", 2)[0]  # https://graph.facebook.com/vXX
        auth = {"Authorization": f"Bearer {self.token}"}
        meta = self.client.get(f"{base}/{media_id}", headers=auth)
        meta.raise_for_status()
        info = meta.json()
        blob = self.client.get(info["url"], headers=auth)
        blob.raise_for_status()
        if len(blob.content) > 20_000_000:
            raise ValueError("attachment too large")
        return blob.content, info.get("mime_type", "application/octet-stream")

    def send_template(self, phone: str, template: str, params: list[str]) -> str | None:
        components = []
        if params:
            components = [{"type": "body", "parameters": [{"type": "text", "text": p[:1000]} for p in params]}]
        return self._post(
            {
                "messaging_product": "whatsapp",
                "to": phone.lstrip("+"),
                "type": "template",
                "template": {"name": template, "language": {"code": self.language}, "components": components},
            }
        )
