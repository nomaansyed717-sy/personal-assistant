from dataclasses import dataclass, field


@dataclass
class InboundMessage:
    phone: str  # E.164
    text: str
    external_id: str
    profile_name: str | None = None
    kind: str = "text"  # text | button | image | document | audio | unsupported
    raw: dict = field(default_factory=dict)
    media_id: str | None = None
    mime: str | None = None
    filename: str | None = None


class Channel:
    """A way to reach the user. WhatsApp today; SMS, iMessage and Telegram plug in here."""

    name = "base"
    # Max characters per message on this channel
    max_len = 4096
    # Whether the channel restricts free-form proactive messages (WhatsApp's 24h rule)
    has_session_window = False

    def send_text(self, phone: str, text: str) -> str | None:
        raise NotImplementedError

    def send_template(self, phone: str, template: str, params: list[str]) -> str | None:
        """Send a pre-approved template (used to reopen a closed session window)."""
        return self.send_text(phone, " ".join(params))

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Return (bytes, mime type) for a media attachment."""
        raise NotImplementedError


class ConsoleChannel(Channel):
    """Development and test channel: records outgoing messages instead of sending them."""

    name = "console"

    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.media: dict[str, tuple[bytes, str]] = {}

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        return self.media[media_id]

    def send_text(self, phone: str, text: str) -> str | None:
        self.sent.append((phone, text))
        print(f"\n[assistant -> {phone}]\n{text}\n")
        return f"console-{len(self.sent)}"

    def send_template(self, phone: str, template: str, params: list[str]) -> str | None:
        self.sent.append((phone, f"[template:{template}] " + " | ".join(params)))
        return f"console-{len(self.sent)}"
