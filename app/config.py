"""Runtime settings, read from environment variables (see .env.example)."""
import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    app_name: str = "Aide"
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

    # The app (Android app + web app) is the main product. Sign-in codes go out by email or SMS.
    # Email: "resend" (RESEND_API_KEY) or "smtp"; anything else logs the code (development only).
    email_provider: str = "console"
    email_from: str = "Aide <hello@example.com>"
    resend_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    # SMS: "msg91" (India, DLT template) or "twilio"; anything else logs the code (development only).
    sms_provider: str = "console"
    msg91_auth_key: str = ""
    msg91_template_id: str = ""  # DLT-approved OTP template with a ##OTP## variable
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""
    # Push notifications through Expo's push service (optional access token for enhanced security)
    expo_access_token: str = ""
    # Extra browser origins allowed to call the API (comma-separated), e.g. the Expo web dev server
    cors_origins: str = ""
    # Deep link scheme of the Android app, used after Google sign-in
    app_scheme: str = "aide"
    # Where people download the Android app (Play Store or an APK link), shown on the homepage
    android_app_url: str = ""

    # WhatsApp Cloud API (Meta). Optional legacy channel: Meta's Business API terms bar
    # general-purpose AI assistants, so the product runs app-first and WhatsApp stays off by default.
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""  # any secret string, also set in the Meta webhook config
    whatsapp_app_secret: str = ""  # used to verify X-Hub-Signature-256
    whatsapp_api_version: str = "v21.0"
    # Telegram (optional): a bot from @BotFather. Users link it from the app; messages and approvals mirror there.
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""  # without the @, e.g. AideAssistantBot
    telegram_webhook_secret: str = ""  # any long random string; Telegram echoes it so we know it's them
    # Approved template used to reopen the 24h window for proactive messages
    whatsapp_reopen_template: str = "assistant_update"
    whatsapp_template_language: str = "en"

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""

    # Web research (either one enables web_search; read_url always works)
    tavily_api_key: str = ""
    brave_api_key: str = ""
    # Voice notes: transcription. Sarvam AI first when set (built for Indian languages and code-mixed speech),
    # then OpenAI. Either is optional; without both, voice notes ask the user to type or use live dictation.
    sarvam_api_key: str = ""
    sarvam_model: str = "saaras:v4"
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
        email_ok = (s.email_provider == "resend" and s.resend_api_key) or (s.email_provider == "smtp" and s.smtp_host)
        sms_ok = (s.sms_provider == "msg91" and s.msg91_auth_key) or (s.sms_provider == "twilio" and s.twilio_account_sid)
        required |= {
            "BASE_URL (https)": s.base_url if s.base_url.startswith("https://") else "",
            "EMAIL_PROVIDER or SMS_PROVIDER (sign-in codes)": "ok" if (email_ok or sms_ok) else "",
        }
        if whatsapp_enabled(s):
            required |= {"WHATSAPP_VERIFY_TOKEN": s.whatsapp_verify_token, "WHATSAPP_APP_SECRET": s.whatsapp_app_secret}
    return [k for k, v in required.items() if not v]


def whatsapp_enabled(s: Settings | None = None) -> bool:
    s = s or get_settings()
    return bool(s.whatsapp_token and s.whatsapp_phone_number_id)
