from app.channels.base import Channel, ConsoleChannel, InboundMessage
from app.config import get_settings

_channel: Channel | None = None


def get_channel() -> Channel:
    """WhatsApp when its credentials are set, otherwise the console channel for development."""
    global _channel
    if _channel is None:
        s = get_settings()
        if s.whatsapp_token and s.whatsapp_phone_number_id:
            from app.channels.whatsapp import WhatsAppChannel

            _channel = WhatsAppChannel()
        else:
            _channel = ConsoleChannel()
    return _channel


def set_channel(channel: Channel | None) -> None:
    """Tests and the local simulator swap the channel here."""
    global _channel
    _channel = channel


__all__ = ["Channel", "ConsoleChannel", "InboundMessage", "get_channel", "set_channel"]
