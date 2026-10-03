"""The Claude adapter speaks the real Messages API shape (checked against a mocked HTTP layer)."""
import json

import anthropic
import httpx2 as httpx

from app.llm import AnthropicLLM


def _client(handler):
    return anthropic.Anthropic(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler)), max_retries=0)


def _msg(content, stop="tool_use"):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "m", "content": content,
            "stop_reason": stop, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}


def test_extract_forces_tool_and_caches_system():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json=_msg([{"type": "tool_use", "id": "tu1", "name": "record", "input": {"x": 1}}]))

    out = AnthropicLLM(_client(handler)).extract("sys", "content", "record", {"type": "object", "properties": {}})
    assert out == {"x": 1}
    assert seen["tool_choice"] == {"type": "tool", "name": "record"}
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert seen["model"] == "claude-haiku-4-5-20251001"


def test_complete_returns_text_and_tool_calls():
    def handler(req):
        return httpx.Response(200, json=_msg([
            {"type": "text", "text": "Checking."},
            {"type": "tool_use", "id": "tu2", "name": "search_email", "input": {"query": "from:ravi"}},
        ]))

    r = AnthropicLLM(_client(handler)).complete("sys", [{"role": "user", "content": "hi"}], [])
    assert r.text == "Checking."
    assert r.tool_calls[0].name == "search_email" and r.tool_calls[0].input == {"query": "from:ravi"}
    assert r.content[1]["type"] == "tool_use"
