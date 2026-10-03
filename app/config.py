"""Runtime settings, read from environment variables (see .env.example)."""
import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    app_name: str = "Assistant"
    base_url: str = "http://localhost:8000"  # public URL, used for OAuth redirects and links
    database_url: str = "postgresql+psycopg://assistant:assistant@localhost:5432/assistant"
    # 32-byte url-safe base64 key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    master_key: str = ""
    env: str = "dev"  # dev | prod

    # Claude
    anthropic_api_key: str = ""
    model_smart: str = "claude-sonnet-5-5"  # planning, drafting, conversation
    model_fast: str = "claude-haiku-4-5-20251001"  # extraction, classification

    # WhatsApp Cloud API (Meta)
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""  # any secret string, also set in the Meta webhook config
    whatsapp_app_secret: str = ""  # used to verify X-Hub-Signature-256
    whatsapp_api_version: str = "v21.0"
    # Approved template used to reopen the 24h window for proactive messages
    whatsapp_reopen_template: str = "assistant_update"
    whatsapp_template_language: str = "en"

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""

    # Behaviour
    default_brief_hour: int = 8  # local time
    undo_window_seconds: int = 60
    raw_retention_days: int = 90
    initial_sync_days: int = 90
    sync_interval_minutes: int = 15
    max_agent_steps: int = 8
    brief_max_items: int = 5


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # On Render, the public URL is provided automatically.
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url and s.base_url == "http://localhost:8000":
        s.base_url = render_url
    return s


def missing_config(s: Settings | None = None) -> list[str]:
    """Settings still to fill in. Only MASTER_KEY is fatal; the rest are reported so setup can happen in stages."""
    s = s or get_settings()
    required = {
        "MASTER_KEY": s.master_key,
        "ANTHROPIC_API_KEY": s.anthropic_api_key,
        "GOOGLE_CLIENT_ID": s.google_client_id,
        "GOOGLE_CLIENT_SECRET": s.google_client_secret,
    }
    if s.env == "prod":
        required |= {
            "BASE_URL (https)": s.base_url if s.base_url.startswith("https://") else "",
            "WHATSAPP_TOKEN": s.whatsapp_token,
            "WHATSAPP_PHONE_NUMBER_ID": s.whatsapp_phone_number_id,
            "WHATSAPP_VERIFY_TOKEN": s.whatsapp_verify_token,
            "WHATSAPP_APP_SECRET": s.whatsapp_app_secret,
        }
    return [k for k, v in required.items() if not v]
