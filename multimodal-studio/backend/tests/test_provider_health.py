"""
Sağlayıcı devre kesici (provider_health) testleri.

Kapsam:
  * 401/403 -> sağlayıcı devre dışı; SONRAKİ çağrılarda hiç istek atılmaz
  * 404     -> yalnızca o model düşer, kardeş model çalışır
  * 429     -> yalnızca o model beklemeye alınır (sağlayıcı kapanmaz)
  * TTL     -> süre dolunca sağlayıcı yeniden denenir
  * Başarı  -> önceki olumsuz karar temizlenir
  * Anahtar değişimi -> devre dışı sıfırlanır
  * Rota     -> /providers gerçek durumu raporlar (uydurma yok)
  * GÜVENLİK -> snapshot sır/anahtar içermez
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ai_agent
import model_routes
from provider_health import ProviderHealth, health


# ------------------------------------------------------------------ yardımcılar

def _ok(content="tamam"):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class _Resp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (str(payload) if payload else "")

    def json(self):
        return self._payload if self._payload is not None else {}


class _FakeClient:
    """Scripted httpx.AsyncClient: (matcher, response) — '' her isteği eşler."""

    scripts = []
    calls = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        model = (json or {}).get("model", "")
        _FakeClient.calls.append({"url": url, "model": model})
        haystack = f"{url} {model}"
        for matcher, action in _FakeClient.scripts:
            if matcher in haystack:
                if isinstance(action, Exception):
                    raise action
                return action
        return _Resp(500, text="unscripted call")


@pytest.fixture(autouse=True)
def _clean_fake():
    _FakeClient.scripts = []
    _FakeClient.calls = []
    yield
    _FakeClient.scripts = []
    _FakeClient.calls = []


def _agent(provider="openrouter", model="m1", key="valid-test-key-123456"):
    a = ai_agent.NexusAIAgent.__new__(ai_agent.NexusAIAgent)
    a.llm_config = SimpleNamespace(
        api_key=key, base_url="https://example.test/v1", model=model,
        temperature=0.7, max_tokens=256,
    )
    a.provider = provider
    a._refresh_llm_config = lambda: None
    return a


async def _rule_based(messages):
    return {"success": True, "rule_based": True,
            "data": {"choices": [{"message": {"role": "assistant", "content": "kural"}}]}}


def _catalog(provider, models, base="https://example.test/v1"):
    return {
        provider: {
            "name": provider,
            "base_url": base,
            "free": True,
            "env_key": f"{provider.upper()}_API_KEY",
            "models": [{"id": m, "name": m} for m in models],
        }
    }


@pytest.fixture
def catalog(monkeypatch):
    def _set(cat, keys):
        monkeypatch.setattr(model_routes, "MODEL_CATALOG", cat)
        cfg = {"active_provider": None, "active_model": None, "api_keys": keys}
        monkeypatch.setattr(model_routes, "_load_config", lambda: cfg)
        monkeypatch.setattr(model_routes, "_save_config", lambda c: None)
        return cfg

    return _set


def _messages():
    return [{"role": "user", "content": "merhaba"}]


# --------------------------------------------------------------- birim: TTL/normal

def test_invalid_provider_blocks_until_ttl_expires():
    now = [1000.0]
    ph = ProviderHealth(clock=lambda: now[0])

    ph.mark_invalid("openrouter", 401, ttl=10)
    assert ph.provider_blocked("openrouter") is True
    assert ph.cooldown_remaining("openrouter") == 10.0

    now[0] += 9
    assert ph.provider_blocked("openrouter") is True

    now[0] += 2
    assert ph.provider_blocked("openrouter") is False, "TTL dolunca yeniden denenmeli"


def test_model_missing_blocks_only_that_model():
    ph = ProviderHealth()
    ph.mark_model_missing("groq", "m1")
    assert ph.model_blocked("groq", "m1") is True
    assert ph.model_blocked("groq", "m2") is False
    assert ph.provider_blocked("groq") is False


def test_rate_limit_caps_wait_and_keeps_provider_open():
    ph = ProviderHealth()
    ph.mark_rate_limited("groq", "m1", wait=9999)
    assert ph.provider_blocked("groq") is False, "429 sağlayıcıyı kapatmamalı"
    assert ph.model_blocked("groq", "m1") is True
    assert ph.snapshot()["blocked_models"]["groq/m1"]["cooldown_seconds"] <= 60


def test_note_success_clears_state():
    ph = ProviderHealth()
    ph.mark_invalid("groq", 401)
    ph.mark_model_missing("groq", "m1")
    ph.note_success("groq", "m1")
    assert ph.provider_blocked("groq") is False
    assert ph.model_blocked("groq", "m1") is False


def test_reset_provider_scoped():
    ph = ProviderHealth()
    ph.mark_invalid("openrouter", 401)
    ph.mark_invalid("openai", 401)
    ph.mark_model_missing("openrouter", "m1")

    ph.reset_provider("openrouter")

    assert ph.provider_blocked("openrouter") is False
    assert ph.model_blocked("openrouter", "m1") is False
    assert ph.provider_blocked("openai") is True, "diğer sağlayıcı etkilenmemeli"


def test_snapshot_contains_no_secrets():
    ph = ProviderHealth()
    ph.mark_invalid("openrouter", 401)
    snap = ph.snapshot()
    assert set(snap) == {"blocked_providers", "blocked_models"}
    entry = snap["blocked_providers"]["openrouter"]
    assert set(entry.keys()) == {"state", "status", "error", "cooldown_seconds"}
    assert entry["error"] == "HTTP 401"
    assert "sk-" not in str(snap), "API anahtari/degeri snapshot'a sizmamali"


# ------------------------------------------------------- entegrasyon: zincir

def test_second_call_skips_provider_with_invalid_key(catalog):
    catalog(_catalog("openrouter", ["m1", "m2", "m3"]),
            {"openrouter": "valid-test-key-123456"})
    _FakeClient.scripts = [("", _Resp(401, text="User not found"))]

    agent = _agent()
    agent._fallback_response = _rule_based

    with patch.object(ai_agent.httpx, "AsyncClient", _FakeClient):
        asyncio.run(agent._fallback_chain(_messages()))
        first_round = len(_FakeClient.calls)
        asyncio.run(agent._fallback_chain(_messages()))
        second_round = len(_FakeClient.calls) - first_round

    assert first_round == 3, "ilk çağrıda kardeş modeller denenir (model bazlı yetki olabilir)"
    assert second_round == 0, "geçersiz anahtarlı sağlayıcı sonraki çağrıda HİÇ denenmemeli"
    assert health.provider_blocked("openrouter") is True


def test_404_blocks_model_but_sibling_model_succeeds(catalog):
    catalog(_catalog("openrouter", ["m1", "m2"]), {"openrouter": "valid-test-key-123456"})
    _FakeClient.scripts = [
        ("m1", _Resp(404, text="model not found")),
        ("m2", _Resp(200, _ok("kurtardı"))),
    ]

    agent = _agent()
    agent._fallback_response = _rule_based

    with patch.object(ai_agent.httpx, "AsyncClient", _FakeClient):
        result = asyncio.run(agent._fallback_chain(_messages()))

    assert result["success"] is True
    assert "kurtardı" in result["data"]["choices"][0]["message"]["content"]
    assert health.model_blocked("openrouter", "m1") is True
    assert health.model_blocked("openrouter", "m2") is False
    assert health.provider_blocked("openrouter") is False


def test_success_after_401_clears_provider_mark(catalog):
    """Bir kardeş model başarılıysa sağlayıcı 'geçersiz' damgası KALMAMALI."""
    catalog(_catalog("openrouter", ["m1", "m2"]), {"openrouter": "valid-test-key-123456"})
    _FakeClient.scripts = [
        ("m1", _Resp(401, text="model yetkisi yok")),
        ("m2", _Resp(200, _ok("çalıştı"))),
    ]

    agent = _agent()
    agent._fallback_response = _rule_based

    with patch.object(ai_agent.httpx, "AsyncClient", _FakeClient):
        result = asyncio.run(agent._fallback_chain(_messages()))

    assert result["success"] is True
    assert health.provider_blocked("openrouter") is False


# ---------------------------------------------------- entegrasyon: _call_llm

def test_call_llm_skips_blocked_provider_without_http():
    health.mark_invalid("openrouter", 401)
    agent = _agent(provider="openrouter")

    seen = {}

    async def fake_chain(messages, **kwargs):
        seen.update(kwargs)
        return {"success": True, "data": _ok("zincirden")}

    agent._fallback_chain = fake_chain

    def boom(*a, **kw):
        raise AssertionError("devre dışı sağlayıcıya HTTP isteği atılmamalı")

    with patch.object(ai_agent.httpx, "AsyncClient", boom):
        result = asyncio.run(agent._call_llm(_messages()))

    assert result["success"] is True
    assert seen.get("failed_provider") == "openrouter"


def test_primary_401_marks_provider_and_next_call_skips(catalog):
    catalog(_catalog("openrouter", ["m1"]), {"openrouter": "valid-test-key-123456"})
    _FakeClient.scripts = [("", _Resp(401, text="Incorrect API key"))]

    agent = _agent(provider="openrouter")
    agent._fallback_response = _rule_based

    with patch.object(ai_agent.httpx, "AsyncClient", _FakeClient):
        asyncio.run(agent._call_llm(_messages()))

    assert health.provider_blocked("openrouter") is True


def test_primary_success_clears_previous_mark():
    agent = _agent(provider="openrouter")
    health.mark_model_missing("openrouter", "m1")
    _FakeClient.scripts = [("", _Resp(200, _ok("merhaba")))]

    with patch.object(ai_agent.httpx, "AsyncClient", _FakeClient):
        result = asyncio.run(agent._call_llm(_messages()))

    assert result["success"] is True
    assert health.model_blocked("openrouter", "m1") is False


# ---------------------------------------------------------------- rota testleri

def _client():
    app = FastAPI()
    app.include_router(model_routes.router)
    return TestClient(app)


def test_providers_route_reports_real_health(monkeypatch):
    monkeypatch.setattr(model_routes, "_load_config", lambda: {"api_keys": {}})
    health.mark_invalid("openrouter", 401)

    body = _client().get("/api/v1/models/providers").json()

    row = next(p for p in body["providers"] if p["id"] == "openrouter")
    assert row["status"] == "invalid_key"
    assert row["last_error"] == "HTTP 401"
    assert row["cooldown_seconds"] > 0
    assert "openrouter" in body["health"]["blocked_providers"]


def test_providers_route_ok_by_default(monkeypatch):
    monkeypatch.setattr(model_routes, "_load_config", lambda: {"api_keys": {}})

    body = _client().get("/api/v1/models/providers").json()

    assert all(p["status"] == "ok" for p in body["providers"])
    assert body["health"]["blocked_providers"] == {}


def test_setting_api_key_resets_provider_health(monkeypatch):
    monkeypatch.setattr(model_routes, "_load_config", lambda: {"api_keys": {}})
    monkeypatch.setattr(model_routes, "_save_config", lambda cfg: None)
    health.mark_invalid("openrouter", 401)

    resp = _client().post(
        "/api/v1/models/api-key",
        json={"provider": "openrouter", "api_key": "sk-or-v1-abcdef1234567890"},
    )

    assert resp.status_code == 200
    assert resp.json()["health_reset"] is True
    assert health.provider_blocked("openrouter") is False, "yeni anahtar hemen denenebilmeli"
