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
    anthropic_workspace_id: str = ""  # only for keys not scoped to a workspace (console > Settings > Workspaces)
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

    # Web research (either one enables web_search; read_url always works)
    tavily_api_key: str = ""
    brave_api_key: str = ""
    # Voice notes: transcription via OpenAI's API (optional)
    openai_api_key: str = ""
    transcribe_model: str = "gpt-4o-mini-transcribe"

    # Secure computer (browser agent)
    browser_enabled: bool = True
    demo_enabled: bool = True  # "Try the live demo" sandbox accounts
    demo_messages: int = 40  # chat messages allowed per demo account
    browser_max_steps: int = 25
    allow_private_urls: bool = False  # tests only; Sentinel blocks internal addresses otherwise

    # Run the scheduler inside the web process (one Railway service). Set false if you run a worker.
    run_worker_in_web: bool = True

    # Public WhatsApp number of the assistant, for wa.me links on the homepage (digits only)
    public_whatsapp_number: str = ""

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
    # On Render and Railway, the public URL is provided automatically.
    if s.base_url == "http://localhost:8000":
        if os.environ.get("RENDER_EXTERNAL_URL"):
            s.base_url = os.environ["RENDER_EXTERNAL_URL"]
        elif os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
            s.base_url = "https://" + os.environ["RAILWAY_PUBLIC_DOMAIN"]
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
