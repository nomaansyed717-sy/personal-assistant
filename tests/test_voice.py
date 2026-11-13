"""Voice in Indian languages: the user's language reaches the transcription provider."""
import httpx
import pytest

from app import media
from app.config import get_settings
from tests.test_app import H, _app_client


class Resp:
    def __init__(self, data):
        self.status_code, self._d, self.text = 200, data, ""

    def json(self):
        return self._d


def test_voice_language_setting_round_trip():
    c, auth = _app_client("voice@example.in")
    assert c.get("/api/me", headers=auth).json()["voice_language"] == "auto"
    assert c.patch("/api/settings", json={"voice_language": "mr-IN"}, headers={**auth, **H}).status_code == 200
    assert c.get("/api/me", headers=auth).json()["voice_language"] == "mr-IN"
    assert c.patch("/api/settings", json={"voice_language": "xx-YY"}, headers={**auth, **H}).status_code == 400
    names = {x["code"]: x["name"] for x in c.get("/api/voice-languages").json()}
    assert names["hi-IN"] == "हिन्दी" and "ta-IN" in names


def test_sarvam_is_preferred_and_gets_the_language(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "sk")
    monkeypatch.setenv("OPENAI_API_KEY", "ok")
    get_settings.cache_clear()
    seen = {}

    def fake_post(url, headers=None, data=None, files=None, timeout=None):
        seen.update(url=url, headers=headers, data=data)
        return Resp({"transcript": "कल सुबह 9 बजे रवि को कॉल करना याद दिलाना"})

    monkeypatch.setattr(httpx, "post", fake_post)
    text = media.transcribe(b"x", "audio/m4a", None, "hi-IN")
    assert "रवि" in text and seen["url"] == "https://api.sarvam.ai/speech-to-text"
    assert seen["headers"] == {"api-subscription-key": "sk"} and seen["data"]["language_code"] == "hi-IN"
    media.transcribe(b"x", "audio/m4a", None, "auto")
    assert seen["data"]["language_code"] == "unknown"
    get_settings.cache_clear()


def test_openai_fallback_uses_iso_language_and_no_provider_explains(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "ok")
    get_settings.cache_clear()
    seen = {}
    monkeypatch.setattr(httpx, "post", lambda url, **kw: seen.update(url=url, **kw) or Resp({"text": "hello"}))
    assert media.transcribe(b"x", "audio/m4a", None, "ta-IN") == "hello"
    assert seen["data"]["language"] == "ta" and "openai.com" in seen["url"]
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(media.MediaError, match="dictate"):
        media.transcribe(b"x", "audio/m4a")
    get_settings.cache_clear()
