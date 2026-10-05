"""The secure computer's browser, driven against a real local website in headless Chromium."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

import pytest

from app import vault
from app.config import get_settings
from app.db import session_scope
from app.execution.browser import run_browser_task
from app.models import User
from tests.fakes import FakeLLM
from tests.helpers import make_active_user

pytest.importorskip("playwright.sync_api")

PAGES = {
    "/": """<html><title>Clinic</title><body><h1>City Dental</h1>
      <form action="/search" method="get"><input name="q" aria-label="Search slots"><button>Search</button></form>
      <a href="/login">Sign in</a></body></html>""",
    "/login": """<html><title>Sign in</title><body><form action="/account" method="post">
      <input name="email" aria-label="Email"><input name="password" type="password" aria-label="Password">
      <button>Sign in</button></form></body></html>""",
    "/checkout": """<html><title>Pay</title><body><input name="cardnumber" autocomplete="cc-number" aria-label="Card number">
      </body></html>""",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, html):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def do_GET(self):
        if self.path.startswith("/search"):
            q = parse_qs(self.path.split("?", 1)[1]).get("q", [""])[0]
            return self._send(f"<html><title>Results</title><body><p>Slots for {q}: Tue 14 Oct 10:00, Thu 16 Oct 15:30</p></body></html>")
        return self._send(PAGES.get(self.path, "<html><body>404</body></html>"))

    def do_POST(self):
        body = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        ok = body.get("email") == ["sam@x.com"] and body.get("password") == ["hunter2"]
        self._send(f"<html><body><p>{'Welcome back Sam' if ok else 'Wrong login'}</p></body></html>")


@pytest.fixture
def site(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE_URLS", "true")
    get_settings.cache_clear()
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    get_settings.cache_clear()


def _llm(steps):
    llm = FakeLLM()
    seq = iter(steps)
    seen = []

    def step(content):
        seen.append(content)
        return next(seq)

    llm.extractors["browser_step"] = step
    return llm, seen


def _index(content, label):
    for line in content.splitlines():
        if line.startswith("[") and repr(label) in line:
            return int(line[1:line.index("]")])
    raise AssertionError(f"{label} not in snapshot")


def test_browser_searches_and_reports(site):
    uid = make_active_user()
    state = {}

    def step(content):
        state.setdefault("n", 0)
        state["n"] += 1
        if state["n"] == 1:
            return {"action": "type", "index": _index(content, "Search slots"), "text": "cleaning"}
        if state["n"] == 2:
            return {"action": "press_enter"}
        assert "Tue 14 Oct 10:00" in content and "<untrusted" in content
        return {"action": "done", "result": "Two slots: Tue 14 Oct 10:00 and Thu 16 Oct 15:30."}

    llm = FakeLLM()
    llm.extractors["browser_step"] = step
    with session_scope() as s:
        out = run_browser_task(s, s.get(User, uid), "Find a cleaning slot", site + "/", llm=llm)
    assert out == "Two slots: Tue 14 Oct 10:00 and Thu 16 Oct 15:30."


def test_login_uses_vault_and_model_cannot_type_passwords(site):
    uid = make_active_user()
    with session_scope() as s:
        vault.add(s, s.get(User, uid), "Clinic", "127.0.0.1", "sam@x.com", "hunter2")
    state = {"n": 0}

    def step(content):
        state["n"] += 1
        assert "hunter2" not in content
        if state["n"] == 1:  # the model tries to type a password itself: refused
            return {"action": "type", "index": _index(content, "Password"), "text": "guess"}
        if state["n"] == 2:
            assert "refused (sensitive" in content
            return {"action": "fill_credential", "index": _index(content, "Email"), "password_index": _index(content, "Password")}
        if state["n"] == 3:
            return {"action": "press_enter"}
        return {"action": "done", "result": content.split("ELEMENTS")[0][-200:] + content[-300:]}

    llm = FakeLLM()
    llm.extractors["browser_step"] = step
    with session_scope() as s:
        out = run_browser_task(s, s.get(User, uid), "Log in", site + "/login", llm=llm)
    assert "Welcome back Sam" in out


def test_payment_pages_hand_off_and_internal_addresses_blocked(site, monkeypatch):
    uid = make_active_user()

    def step(content):
        assert "(sensitive: never type)" in content
        return {"action": "handoff", "result": "Checkout needs your card"}

    llm = FakeLLM()
    llm.extractors["browser_step"] = step
    with session_scope() as s:
        out = run_browser_task(s, s.get(User, uid), "Buy it", site + "/checkout", llm=llm)
    assert out.startswith("Over to you: Checkout needs your card")

    monkeypatch.setenv("ALLOW_PRIVATE_URLS", "false")
    get_settings.cache_clear()
    from app.execution import ExecutionError

    with session_scope() as s, pytest.raises(ExecutionError, match="Sentinel"):
        run_browser_task(s, s.get(User, uid), "x", site + "/", llm=llm)
