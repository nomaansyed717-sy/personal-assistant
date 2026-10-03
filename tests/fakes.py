"""In-memory stand-ins for Google, Claude and WhatsApp, so the whole product runs offline in tests."""
import base64
import json
from datetime import UTC, datetime, timedelta
from email import message_from_bytes
from urllib.parse import parse_qs

import httpx

from app.llm import LLM, LLMResponse, ToolCall


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


class FakeGoogle:
    """Serves the Google OAuth, Gmail and Calendar endpoints the app uses."""

    def __init__(self, account="me@example.com"):
        self.account = account
        self.messages: dict[str, dict] = {}
        self.sent: list[dict] = []
        self.events: list[dict] = []
        self.created_events: list[dict] = []
        self.revoked: list[str] = []
        self.refreshes = 0

    def add_email(self, mid, thread, frm, to, subject, body, when: datetime, sent=False, newsletter=False, from_name=""):
        headers = [
            {"name": "From", "value": f"{from_name} <{frm}>" if from_name else frm},
            {"name": "To", "value": ", ".join(to)},
            {"name": "Subject", "value": subject},
            {"name": "Date", "value": when.strftime("%a, %d %b %Y %H:%M:%S +0000")},
            {"name": "Message-ID", "value": f"<{mid}@mail.example.com>"},
        ]
        if newsletter:
            headers.append({"name": "List-Unsubscribe", "value": "<mailto:u@x.com>"})
        self.messages[mid] = {
            "id": mid,
            "threadId": thread,
            "labelIds": ["SENT"] if sent else ["INBOX"],
            "snippet": body[:80],
            "internalDate": str(int(when.timestamp() * 1000)),
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": headers,
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": _b64(body)}},
                    {"mimeType": "text/html", "body": {"data": _b64(f"<div>{body}</div>")}},
                ],
            },
        }

    def add_event(self, eid, title, start: datetime, minutes=30, attendees=()):
        self.events.append(
            {
                "id": eid,
                "status": "confirmed",
                "summary": title,
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": (start + timedelta(minutes=minutes)).isoformat()},
                "attendees": [{"email": a} for a in attendees],
            }
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        path = request.url.path
        if url.startswith("https://oauth2.googleapis.com/token"):
            form = parse_qs(request.content.decode())
            if form.get("grant_type") == ["refresh_token"]:
                self.refreshes += 1
            return httpx.Response(
                200,
                json={"access_token": "at-123", "refresh_token": "rt-456", "expires_in": 3600, "scope": "gmail calendar"},
            )
        if url.startswith("https://oauth2.googleapis.com/revoke"):
            self.revoked.append(request.url.params.get("token"))
            return httpx.Response(200, json={})
        if url.startswith("https://openidconnect.googleapis.com/v1/userinfo"):
            return httpx.Response(200, json={"email": self.account})
        if path == "/gmail/v1/users/me/messages" and request.method == "GET":
            return httpx.Response(200, json={"messages": [{"id": k} for k in self.messages]})
        if path.startswith("/gmail/v1/users/me/messages/") and request.method == "GET":
            mid = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=self.messages[mid])
        if path == "/gmail/v1/users/me/messages/send":
            body = json.loads(request.content)
            raw = base64.urlsafe_b64decode(body["raw"] + "==")
            msg = message_from_bytes(raw)
            self.sent.append(
                {
                    "to": msg["To"],
                    "subject": msg["Subject"],
                    "in_reply_to": msg["In-Reply-To"],
                    "thread_id": body.get("threadId"),
                    "body": msg.get_payload(decode=True).decode() if not msg.is_multipart() else "",
                }
            )
            return httpx.Response(200, json={"id": f"sent-{len(self.sent)}"})
        if path == "/calendar/v3/calendars/primary/events" and request.method == "GET":
            return httpx.Response(200, json={"items": self.events})
        if path == "/calendar/v3/calendars/primary/events" and request.method == "POST":
            ev = json.loads(request.content)
            self.created_events.append(ev)
            return httpx.Response(200, json={"id": f"ev-{len(self.created_events)}"})
        if path == "/calendar/v3/freeBusy":
            busy = [{"start": e["start"]["dateTime"], "end": e["end"]["dateTime"]} for e in self.events]
            return httpx.Response(200, json={"calendars": {"primary": {"busy": busy}}})
        return httpx.Response(404, json={"error": f"unhandled {request.method} {url}"})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


class FakeLLM(LLM):
    """Scripted model. `extractors` maps a tool name to a function(content) -> dict.
    `turns` is a list of LLMResponse objects returned by complete(), in order."""

    def __init__(self):
        self.extractors = {}
        self.turns: list[LLMResponse] = []
        self.extract_calls: list[tuple[str, str]] = []
        self.complete_calls: list[list[dict]] = []

    def extract(self, system, content, name, schema, fast=True):
        self.extract_calls.append((name, content))
        fn = self.extractors.get(name)
        return fn(content) if fn else {}

    def complete(self, system, messages, tools, max_tokens=1500):
        self.complete_calls.append([dict(m) for m in messages])
        if self.turns:
            return self.turns.pop(0)
        return LLMResponse(text="(no scripted reply)")

    @staticmethod
    def tool(name, args, call_id="t1") -> LLMResponse:
        return LLMResponse(
            text="",
            tool_calls=[ToolCall(id=call_id, name=name, input=args)],
            content=[{"type": "tool_use", "id": call_id, "name": name, "input": args}],
        )

    @staticmethod
    def say(text) -> LLMResponse:
        return LLMResponse(text=text, content=[{"type": "text", "text": text}])


def now():
    return datetime.now(UTC)
