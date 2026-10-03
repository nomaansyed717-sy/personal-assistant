"""Thin wrapper around the Claude API so the rest of the app (and the tests) don't
depend on SDK details. Two calls:

- extract(): force a single tool call to get structured JSON back.
- complete(): one turn of a tool-using conversation (the agent loop drives it).
"""
import json
import logging
from dataclasses import dataclass, field

from app.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    content: list[dict] = field(default_factory=list)  # raw assistant content blocks, to replay in the loop


class LLM:
    def extract(self, system: str, content: str, name: str, schema: dict, fast: bool = True) -> dict:
        raise NotImplementedError

    def complete(self, system: str, messages: list[dict], tools: list[dict], max_tokens: int = 1500) -> LLMResponse:
        raise NotImplementedError


class AnthropicLLM(LLM):
    def __init__(self, client=None):
        import anthropic

        s = get_settings()
        self.client = client or anthropic.Anthropic(api_key=s.anthropic_api_key, max_retries=3)
        self.smart = s.model_smart
        self.fast = s.model_fast

    @staticmethod
    def _system(system: str) -> list[dict]:
        # Cache the long, stable system prompt across calls.
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    def extract(self, system: str, content: str, name: str, schema: dict, fast: bool = True) -> dict:
        resp = self.client.messages.create(
            model=self.fast if fast else self.smart,
            max_tokens=4000,
            system=self._system(system),
            messages=[{"role": "user", "content": content}],
            tools=[{"name": name, "description": f"Return the {name} result.", "input_schema": schema}],
            tool_choice={"type": "tool", "name": name},
        )
        for block in resp.content:
            if block.type == "tool_use":
                return dict(block.input)
        log.warning("extract(%s) returned no tool call", name)
        return {}

    def complete(self, system: str, messages: list[dict], tools: list[dict], max_tokens: int = 1500) -> LLMResponse:
        resp = self.client.messages.create(
            model=self.smart,
            max_tokens=max_tokens,
            system=self._system(system),
            messages=messages,
            tools=tools,
        )
        text, calls, content = [], [], []
        for block in resp.content:
            if block.type == "text":
                text.append(block.text)
                content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input)))
                content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": dict(block.input)})
        return LLMResponse(text="\n".join(text).strip(), tool_calls=calls, content=content)


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = AnthropicLLM()
    return _llm


def set_llm(llm: LLM | None) -> None:
    global _llm
    _llm = llm


def untrusted(label: str, text: str) -> str:
    """Wrap outside content so the model treats it as data, never as instructions."""
    safe = (text or "").replace("</untrusted", "</ untrusted")
    return f'<untrusted source="{label}">\n{safe}\n</untrusted>'


def to_json(obj) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)
