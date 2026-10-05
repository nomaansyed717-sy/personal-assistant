"""Turn WhatsApp attachments into something the model can use: images and PDFs go to Claude
directly; voice notes are transcribed (OpenAI transcription API, optional)."""
import base64
import logging

import httpx

from app.channels import InboundMessage, get_channel
from app.config import get_settings

log = logging.getLogger(__name__)
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class MediaError(Exception):
    pass


def prepare(msg: InboundMessage) -> tuple[str, list[dict]]:
    """Return (text for the agent, content blocks to attach)."""
    if not msg.media_id:
        return msg.text, []
    data, mime = get_channel().download_media(msg.media_id)
    mime = (msg.mime or mime or "").split(";")[0].strip().lower()
    caption = msg.text or ""
    if msg.kind == "audio" or mime.startswith("audio/"):
        return transcribe(data, mime, msg.filename), []
    b64 = base64.standard_b64encode(data).decode()
    if mime in IMAGE_TYPES:
        return caption or "(The user sent this photo without a caption. Work out what they likely want.)", [
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}
        ]
    if mime == "application/pdf":
        return caption or f"(The user sent the document {msg.filename or 'a PDF'} without a caption.)", [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
        ]
    if mime.startswith("text/"):
        return (caption + "\n\n" if caption else "") + data.decode("utf-8", errors="replace")[:20000], []
    raise MediaError(f"I can read photos, PDFs, text files and voice notes, but not {mime or 'this file type'} yet.")


def transcribe(data: bytes, mime: str, filename: str | None = None) -> str:
    s = get_settings()
    if not s.openai_api_key:
        raise MediaError("Voice notes need transcription switched on (OPENAI_API_KEY). Please type it for now.")
    ext = {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/aac": "aac", "audio/amr": "amr"}.get(mime, "ogg")
    r = httpx.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {s.openai_api_key}"},
        data={"model": s.transcribe_model},
        files={"file": (filename or f"voice.{ext}", data, mime or "audio/ogg")},
        timeout=60,
    )
    if r.status_code >= 400:
        log.error("transcription failed %s: %s", r.status_code, r.text[:300])
        raise MediaError("I couldn't make out that voice note. Could you type it?")
    text = r.json().get("text", "").strip()
    if not text:
        raise MediaError("That voice note seemed empty.")
    return text
