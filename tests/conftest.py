import os

from cryptography.fernet import Fernet

# Settings are read from the environment, so configure before importing the app.
os.environ.setdefault("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", "sqlite:///./test.db"))
os.environ["MASTER_KEY"] = Fernet.generate_key().decode()
os.environ["ENV"] = "dev"
os.environ["BASE_URL"] = "https://assistant.test"
os.environ["GOOGLE_CLIENT_ID"] = "cid"
os.environ["GOOGLE_CLIENT_SECRET"] = "secret"
os.environ["WHATSAPP_TOKEN"] = ""
os.environ["WHATSAPP_APP_SECRET"] = ""
os.environ["APP_NAME"] = "Aide"

import pytest  # noqa: E402

from app import channels, db, llm  # noqa: E402
from app.channels.base import ConsoleChannel  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.integrations import google  # noqa: E402
from tests.fakes import FakeGoogle, FakeLLM  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    get_settings.cache_clear()
    db.reset_engine()
    from app import models  # noqa: F401

    engine = db.get_engine()
    db.Base.metadata.drop_all(engine)
    db.Base.metadata.create_all(engine)
    yield
    db.reset_engine()


@pytest.fixture
def channel():
    ch = ConsoleChannel()
    channels.set_channel(ch)
    yield ch
    channels.set_channel(None)


@pytest.fixture
def fake_google():
    g = FakeGoogle()
    google.set_http(g.client())
    yield g
    google.set_http(None)


@pytest.fixture
def fake_llm():
    f = FakeLLM()
    llm.set_llm(f)
    yield f
    llm.set_llm(None)
