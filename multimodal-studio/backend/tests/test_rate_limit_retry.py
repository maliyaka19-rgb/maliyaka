"""Regression tests for LLM rate-limit (429) handling.

Root cause of the "Uzgunum, su anda tam yanit uretemiyorum..." error on
multi-step tasks: a Groq 429 (per-minute token cap) immediately cascaded into
the fallback chain, which *dropped* the only working provider (Groq) and left
nothing but the rule-based fallback.

These tests are mock-based (no network) and run with the default suite.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

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
    """Build a NexusAIAgent without running __init__ (no real config/env)."""
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

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            return post_impl()

    monkeypatch.setattr(ai_agent.httpx, "AsyncClient", _Client)
    # Avoid real sleeping during retries.
    monkeypatch.setattr(ai_agent, "_parse_retry_after", lambda resp, default=20.0: 0.0)
    return agent


# ------------------------ _parse_retry_after ------------------------

def test_parse_retry_after_header():
    r = _Resp(429, {"error": {}}, headers={"retry-after": "12"})
    assert ai_agent._parse_retry_after(r) == 12.0


def test_parse_retry_after_body_seconds():
    r = _Resp(429, text="Rate limit reached. Please try again in 7.5s.")
    assert 7.5 <= ai_agent._parse_retry_after(r) <= 9.0


def test_parse_retry_after_body_minutes():
    r = _Resp(429, text="Please try again in 1m30s.")
    assert 90.0 <= ai_agent._parse_retry_after(r) <= 92.0


def test_parse_retry_after_default_when_unparseable():
    r = _Resp(429, text="totally unparseable")
    assert ai_agent._parse_retry_after(r, default=15.0) == 15.0


def test_parse_retry_after_header_is_capped():
    r = _Resp(429, headers={"retry-after": "9999"})
    assert ai_agent._parse_retry_after(r) == 90.0


# ------------------------ _call_llm retry ------------------------

def test_call_llm_retries_429_then_succeeds(monkeypatch):
    state = {"n": 0}

    def post():
        state["n"] += 1
        if state["n"] <= 2:
            return _Resp(429, {"error": {"message": "try again in 1s"}})
        return _Resp(200, {"choices": [{"message": {"role": "assistant", "content": "Selam"}}]})

    agent = _make_agent(monkeypatch, post)
    result = asyncio.run(agent._call_llm([{"role": "user", "content": "merhaba"}]))
    assert result["success"] is True
    assert result["data"]["choices"][0]["message"]["content"] == "Selam"
    assert state["n"] == 3  # 2 x 429 (retried) + 1 success


def test_call_llm_exhausted_429_marks_fallback_rate_limited(monkeypatch):
    def post():
        return _Resp(429, {"error": {"message": "try again in 1s"}})

    agent = _make_agent(monkeypatch, post)
    captured = {}

    async def fake_fallback(messages, failed_provider=None, failed_model=None, rate_limited=False):
        captured.update(
            failed_provider=failed_provider,
            failed_model=failed_model,
            rate_limited=rate_limited,
        )
        return {"success": True, "data": {"choices": [{"message": {"role": "assistant", "content": "fb"}}]}}

    agent._fallback_chain = fake_fallback
    result = asyncio.run(agent._call_llm([{"role": "user", "content": "x"}]))
    assert result["data"]["choices"][0]["message"]["content"] == "fb"
    assert captured["failed_provider"] == "groq"
    assert captured["rate_limited"] is True


def test_call_llm_uses_retry_budget(monkeypatch):
    """Total attempts should be exactly _RATE_LIMIT_MAX_RETRIES + 1."""
    state = {"n": 0}

    def post():
        state["n"] += 1
        return _Resp(429, {"error": {"message": "try again in 1s"}})

    agent = _make_agent(monkeypatch, post)

    async def fake_fallback(messages, failed_provider=None, failed_model=None, rate_limited=False):
        return {"success": True, "data": {"choices": [{"message": {"role": "assistant", "content": "fb"}}]}}

    agent._fallback_chain = fake_fallback
    asyncio.run(agent._call_llm([{"role": "user", "content": "x"}]))
    assert state["n"] == ai_agent._RATE_LIMIT_MAX_RETRIES + 1


# ------------------------ _fallback_chain provider retention ------------------------

def test_fallback_keeps_rate_limited_provider(monkeypatch):
    """A rate-limited provider must NOT be dropped: its sibling models have
    independent quota buckets and should be tried first."""
    import model_routes

    catalog = {
        "groq": {
            "env_key": "GROQ_API_KEY",
            "base_url": "https://api.groq.com/openai/v1",
            "models": [
                {"id": "openai/gpt-oss-120b"},
                {"id": "llama-3.3-70b-versatile"},
            ],
        },
        "openai": {
            "env_key": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "models": [{"id": "gpt-4o"}],
        },
    }
    monkeypatch.setattr(model_routes, "MODEL_CATALOG", catalog)
    monkeypatch.setattr(model_routes, "_is_valid_key", lambda k: bool(k))
    monkeypatch.setattr(model_routes, "_load_config", lambda: {"api_keys": {"groq": "groq-key-1234567890"}})
    monkeypatch.setattr(model_routes, "_save_config", lambda cfg: None)

    tried = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            tried.append(json["model"])
            return _Resp(200, {"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr(ai_agent.httpx, "AsyncClient", _Client)

    agent = ai_agent.NexusAIAgent.__new__(ai_agent.NexusAIAgent)
    agent.llm_config = SimpleNamespace(api_key="", base_url="", model="", temperature=0.7, max_tokens=4096)
    agent.provider = "groq"

    result = asyncio.run(agent._fallback_chain(
        [{"role": "user", "content": "x"}],
        failed_provider="groq",
        failed_model="openai/gpt-oss-120b",
        rate_limited=True,
    ))

    assert result["success"] is True
    assert tried, "fallback should have attempted a request"
    assert tried[0] == "llama-3.3-70b-versatile", "sibling model of rate-limited provider tried first"
    assert "openai/gpt-oss-120b" not in tried, "the already rate-limited model is skipped"


def test_fallback_drops_provider_on_hard_failure(monkeypatch):
    """A non-rate-limit failure (e.g. bad auth) should still drop the provider."""
    import model_routes

    catalog = {
        "groq": {
            "env_key": "GROQ_API_KEY",
            "base_url": "https://api.groq.com/openai/v1",
            "models": [{"id": "openai/gpt-oss-120b"}, {"id": "llama-3.3-70b-versatile"}],
        },
        "openai": {
            "env_key": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "models": [{"id": "gpt-4o"}],
        },
    }
    monkeypatch.setattr(model_routes, "MODEL_CATALOG", catalog)
    monkeypatch.setattr(model_routes, "_is_valid_key", lambda k: bool(k))
    monkeypatch.setattr(model_routes, "_load_config", lambda: {"api_keys": {"groq": "groq-key-1234567890", "openai": "openai-key-1234567890"}})
    monkeypatch.setattr(model_routes, "_save_config", lambda cfg: None)

    tried = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            tried.append(json["model"])
            return _Resp(200, {"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr(ai_agent.httpx, "AsyncClient", _Client)

    agent = ai_agent.NexusAIAgent.__new__(ai_agent.NexusAIAgent)
    agent.llm_config = SimpleNamespace(api_key="", base_url="", model="", temperature=0.7, max_tokens=4096)
    agent.provider = "groq"

    asyncio.run(agent._fallback_chain(
        [{"role": "user", "content": "x"}],
        failed_provider="groq",
        failed_model="openai/gpt-oss-120b",
        rate_limited=False,
    ))

    assert "gpt-4o" in tried, "next provider (openai) should be used"
    assert "llama-3.3-70b-versatile" not in tried, "failed (dropped) provider's models are not retried"
