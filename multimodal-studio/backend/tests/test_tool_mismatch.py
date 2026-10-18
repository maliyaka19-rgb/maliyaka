"""Regression tests for provider "tool call validation failed" (HTTP 400).

Root cause of a long stall + degraded answers: some models (e.g. `gpt-oss-120b`
on Groq) sometimes emit a tool call for a tool that was NOT advertised in
`request.tools` (for example `write_file`). The provider rejects the entire turn
with a 400, which previously cascaded through the whole 20+ provider fallback
chain and often ended in the rule-based fallback.

Fix: on such a 400 we retry the SAME model once with tools disabled, turning the
turn into a normal text answer.

These tests are mock-based (no network).
"""
import asyncio
import json
from types import SimpleNamespace

import ai_agent


class _Resp:
    def __init__(self, status_code, payload=None, headers=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        return self._payload


def _make_agent(monkeypatch, post_impl):
    agent = ai_agent.NexusAIAgent.__new__(ai_agent.NexusAIAgent)
    agent.llm_config = SimpleNamespace(
        api_key="test-key-abcdef123456",
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-120b",
        temperature=0.7,
        max_tokens=4096,
    )
    agent.provider = "groq"
    agent._refresh_llm_config = lambda: None

    calls = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            calls.append(json)
            return post_impl(json)

    monkeypatch.setattr(ai_agent.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ai_agent, "_parse_retry_after", lambda resp, default=20.0: 0.0)
    return agent, calls


def test_tool_validation_400_retries_with_tools_disabled(monkeypatch):
    def post(payload):
        if "tools" in payload:
            return _Resp(
                400,
                text=json.dumps(
                    {
                        "error": {
                            "message": "Tool call validation failed: attempted to call "
                            "tool 'write_file' which was not in request.tools"
                        }
                    }
                ),
            )
        return _Resp(200, {"choices": [{"message": {"role": "assistant", "content": "duz yanit"}}]})

    agent, calls = _make_agent(monkeypatch, post)
    result = asyncio.run(agent._call_llm([{"role": "user", "content": "x"}]))

    assert result["success"] is True
    assert result["data"]["choices"][0]["message"]["content"] == "duz yanit"
    assert result.get("tools_disabled") is True
    # first attempt advertised tools, the retry must NOT
    assert "tools" in calls[0]
    assert "tools" not in calls[1]
    assert "tool_choice" not in calls[1]


def test_tool_validation_400_retry_failure_falls_back(monkeypatch):
    def post(payload):
        return _Resp(
            400,
            text="Tool call validation failed: attempted to call tool 'write_file' "
            "which was not in request.tools",
        )

    agent, calls = _make_agent(monkeypatch, post)
    captured = {}

    async def fake_fallback(messages, failed_provider=None, failed_model=None, rate_limited=False):
        captured.update(provider=failed_provider, model=failed_model, rate_limited=rate_limited)
        return {"success": True, "data": {"choices": [{"message": {"role": "assistant", "content": "fb"}}]}}

    agent._fallback_chain = fake_fallback
    result = asyncio.run(agent._call_llm([{"role": "user", "content": "x"}]))

    assert result["data"]["choices"][0]["message"]["content"] == "fb"
    # original + one tool-disabled retry, then fallback
    assert len(calls) == 2
    assert captured["provider"] == "groq"
    assert captured["rate_limited"] is False


def test_unrelated_400_does_not_trigger_tool_retry(monkeypatch):
    def post(payload):
        return _Resp(400, text=json.dumps({"error": {"message": "invalid model"}}))

    agent, calls = _make_agent(monkeypatch, post)

    async def fake_fallback(messages, failed_provider=None, failed_model=None, rate_limited=False):
        return {"success": True, "data": {"choices": [{"message": {"role": "assistant", "content": "fb"}}]}}

    agent._fallback_chain = fake_fallback
    asyncio.run(agent._call_llm([{"role": "user", "content": "x"}]))
    assert len(calls) == 1, "a non-tool 400 must go straight to fallback"
