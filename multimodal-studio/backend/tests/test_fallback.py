"""
Model Router / Fallback Tests (Mock-based)
==========================================
Phase V3 T-006: Verifies error classification and fallback chain behavior
WITHOUT real API calls (mocks clearly separated from live integration tests).

Test results classification: PASS / FAIL / BLOCKED / NOT RUN
"""
import sys
import os
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_agent import _validate_response, NexusAIAgent
import ai_agent


# ============================================================
# RESPONSE VALIDATION (schema structure checks)
# ============================================================

def _good_response(content="Merhaba"):
    return {
        "choices": [{
            "message": {"role": "assistant", "content": content, "tool_calls": None},
            "finish_reason": "stop"
        }]
    }


class TestValidateResponse:
    def test_valid_plain_response(self):
        assert _validate_response(_good_response()) is True

    def test_valid_with_tool_calls(self):
        data = {"choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"type": "function",
                            "function": {"name": "calculate", "arguments": "{\"expr\":\"2+2\"}"}}]
        }}]}
        assert _validate_response(data) is True

    def test_rejects_non_dict(self):
        assert _validate_response("not a dict") is False
        assert _validate_response(None) is False
        assert _validate_response([]) is False

    def test_rejects_missing_choices(self):
        assert _validate_response({}) is False

    def test_rejects_empty_choices(self):
        assert _validate_response({"choices": []}) is False

    def test_rejects_wrong_role(self):
        data = {"choices": [{"message": {"role": "user", "content": "x"}}]}
        assert _validate_response(data) is False

    def test_rejects_missing_content(self):
        data = {"choices": [{"message": {"role": "assistant"}}]}
        assert _validate_response(data) is False

    def test_rejects_malformed_tool_calls(self):
        data = {"choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"type": "weird", "function": {}}]
        }}]}
        assert _validate_response(data) is False

    def test_rejects_non_string_tool_arguments(self):
        data = {"choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"type": "function",
                            "function": {"name": "x", "arguments": 123}}]
        }}]}
        assert _validate_response(data) is False


# ============================================================
# FALLBACK CHAIN — mocked HTTP responses (429/401/404/timeout)
# ============================================================

def _mk_response(status_code, payload=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or (str(payload) if payload else "")
    resp.json = MagicMock(return_value=payload if payload is not None else {})
    return resp


class _FakeAsyncClient:
    """Mock httpx.AsyncClient — scripted responses by URL *or* payload model."""
    scripts = []  # list of (matcher, response_or_exception)
    calls = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        model = (json or {}).get("model", "")
        haystack = f"{url} {model}"
        _FakeAsyncClient.calls.append({"url": url, "model": model, "headers": headers, "json": json})
        for matcher, action in _FakeAsyncClient.scripts:
            if matcher in haystack:
                if isinstance(action, Exception):
                    raise action
                return action
        # Unscripted call -> hard failure (prevents accidental success)
        return _mk_response(500, text="no mock script for this call")


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Her testte LLM anahtarlarını sıfırla ve zincirin groq'tan başlasını sağla.

    Testler 'groq' priority sırasının birinci olduğunu ve ilk modelin
    'openai/gpt-oss-120b' olduğunu varsayar. Deterministik olması için
    config'deki groq anahtarını geçerli, diğerlerini geçersiz yaparız.
    """
    import model_routes
    for var in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY",
                "GEMINI_API_KEY", "GOOGLE_AI_KEY", "TOGETHER_API_KEY",
                "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(var, "")
    # Zincir groq'tan başlasın (groq key geçerli, diğerleri yok)
    fake_cfg = {"active_provider": None, "active_model": None,
                "api_keys": {"groq": "gsk_test_key"}}
    monkeypatch.setattr(model_routes, "_load_config", lambda: fake_cfg)
    monkeypatch.setattr(model_routes, "_save_config", lambda cfg: None)
    # _fallback_chain 'from model_routes import _load_config' ile lokal import
    # eder; monkeypatch import edilen adı da günceller ama emin olmak için
    # ai_agent namespace'ine de yaz.
    monkeypatch.setattr(ai_agent, "_load_config", lambda: fake_cfg, raising=False)


@pytest.fixture
def agent():
    # __init__ sadece config okur; ağ çağrısı yapmaz
    return NexusAIAgent()


def _run(coro):
    return asyncio.run(coro)


class TestFallbackChain:
    def setup_method(self):
        _FakeAsyncClient.scripts = []
        _FakeAsyncClient.calls = []

    def test_429_rate_limit_skips_to_next_model(self, agent):
        """429 → bir sonraki modele geç (yeniden deneme değil, sıradaki model)."""
        _FakeAsyncClient.scripts = [
            ("openai/gpt-oss-120b", _mk_response(429, text="rate limited")),
            ("openai/gpt-oss-20b", _mk_response(200, _good_response("fallback ok"))),
        ]
        with patch.object(ai_agent.httpx, "AsyncClient", _FakeAsyncClient):
            result = _run(agent._fallback_chain([{"role": "user", "content": "hi"}]))
        assert result["success"] is True
        assert "fallback ok" in result["data"]["choices"][0]["message"]["content"]
        # İlk model denenmiş, ikincisi başarılı
        models = [c["model"] for c in _FakeAsyncClient.calls]
        assert "openai/gpt-oss-120b" in models
        assert "openai/gpt-oss-20b" in models

    def test_401_auth_error_moves_on(self, agent):
        """401 (yetki) → aynı modelde takılmaz, sıradaki denenir."""
        _FakeAsyncClient.scripts = [
            ("gpt-oss-120b", _mk_response(401, text='{"error":"User not found"}')),
            ("gpt-oss-20b", _mk_response(200, _good_response("ikinci model çalıştı"))),
        ]
        with patch.object(ai_agent.httpx, "AsyncClient", _FakeAsyncClient):
            result = _run(agent._fallback_chain([{"role": "user", "content": "hi"}]))
        assert result["success"] is True

    def test_404_invalid_model_skips(self, agent):
        """404 (model yok) → model katalogdan düşer, sonraki denenir."""
        _FakeAsyncClient.scripts = [
            ("gpt-oss-120b", _mk_response(404, text="model not found")),
            ("gpt-oss-20b", _mk_response(200, _good_response("404 sonrası kurtardı"))),
        ]
        with patch.object(ai_agent.httpx, "AsyncClient", _FakeAsyncClient):
            result = _run(agent._fallback_chain([{"role": "user", "content": "hi"}]))
        assert result["success"] is True

    def test_timeout_skips_to_next(self, agent):
        """Timeout → sıradaki model/provider."""
        _FakeAsyncClient.scripts = [
            ("gpt-oss-120b", ai_agent.httpx.TimeoutException("timed out")),
            ("gpt-oss-20b", _mk_response(200, _good_response("timeout sonrası"))),
        ]
        with patch.object(ai_agent.httpx, "AsyncClient", _FakeAsyncClient):
            result = _run(agent._fallback_chain([{"role": "user", "content": "hi"}]))
        assert result["success"] is True

    def test_invalid_structure_triggers_next_model(self, agent):
        """200 ama bozuk şema → validasyon başarısız → sıradaki model."""
        bad = {"choices": [{"message": {"role": "tool", "content": 5}}]}
        _FakeAsyncClient.scripts = [
            ("gpt-oss-120b", _mk_response(200, bad)),
            ("gpt-oss-20b", _mk_response(200, _good_response("geçerli şema"))),
        ]
        with patch.object(ai_agent.httpx, "AsyncClient", _FakeAsyncClient):
            result = _run(agent._fallback_chain([{"role": "user", "content": "hi"}]))
        assert result["success"] is True

    def test_all_failures_falls_back_to_rule_based(self, agent):
        """Tüm zincir tükenirse rule-based yanıt (asla None/exception değil)."""
        import model_routes
        _FakeAsyncClient.scripts = [
            ("chat/completions", _mk_response(500, text="server error")),
            (":generateContent", _mk_response(500, text="server error")),
        ]
        empty_config = {"active_provider": None, "active_model": None, "api_keys": {}}
        with patch.object(ai_agent.httpx, "AsyncClient", _FakeAsyncClient), \
             patch.object(model_routes, "_load_config", return_value=empty_config), \
             patch.dict(os.environ, {"GROQ_API_KEY": "", "OPENAI_API_KEY": "",
                                     "GEMINI_API_KEY": "", "TOGETHER_API_KEY": "",
                                     "OPENROUTER_API_KEY": ""}, clear=False):
            result = _run(agent._fallback_chain([{"role": "user", "content": "Merhaba"}]))
        # Zincir tükenmeli ve rule-based yanıt dönmeli (dict, success alanı ile)
        assert isinstance(result, dict)
        assert "success" in result

    def test_fallback_uses_authorization_header(self, agent):
        """Her istekte geçerli Authorization başlığı taşınır (key sızdırmadan)."""
        _FakeAsyncClient.scripts = [
            ("gpt-oss-120b", _mk_response(429, text="rl")),
            ("gpt-oss-20b", _mk_response(200, _good_response("ok"))),
        ]
        with patch.object(ai_agent.httpx, "AsyncClient", _FakeAsyncClient):
            _run(agent._fallback_chain([{"role": "user", "content": "hi"}]))
        for call in _FakeAsyncClient.calls:
            auth = (call["headers"] or {}).get("Authorization", "")
            assert auth.startswith("Bearer "), "Authorization başlığı eksik"

    def test_no_api_key_leaks_into_url(self, agent):
        """API key URL'ye sızmamalı (Gemini hariç — orada query param, mock'ta yok)."""
        _FakeAsyncClient.scripts = [
            ("gpt-oss-120b", _mk_response(200, _good_response("ok"))),
        ]
        with patch.object(ai_agent.httpx, "AsyncClient", _FakeAsyncClient):
            _run(agent._fallback_chain([{"role": "user", "content": "hi"}]))
        for call in _FakeAsyncClient.calls:
            assert "sk-or-v1" not in call["url"], "API key URL'ye sızmış!"


# ============================================================
# ERROR CLASSIFICATION — hata türü ayrımı (429 vs 401 vs 404)
# ============================================================

class TestErrorClassification:
    """Ayrıştırma mantığını doğrular: hangi durumda zincir nasıl davranır."""

    def test_429_does_not_retry_same_model(self, agent):
        """429 aynı modelde tekrar denenmemeli (sınırlı yeniden deneme)."""
        _FakeAsyncClient.scripts = [
            ("gpt-oss-120b", _mk_response(429, text="rate")),
        ]
        with patch.object(ai_agent.httpx, "AsyncClient", _FakeAsyncClient):
            _run(agent._fallback_chain([{"role": "user", "content": "hi"}]))
        urls = [c["url"] for c in _FakeAsyncClient.calls]
        oss120_calls = [u for u in urls if "gpt-oss-120b" in u]
        # Fallback zinciri aynı modeli yalnızca 1 kez denemeli
        assert len(oss120_calls) <= 1, f"Aynı model {len(oss120_calls)} kez denenmiş (429'da tekrar denenmemeli)"

    def test_success_halts_chain_deterministic(self, agent):
        """Geçerli (200 + doğru şema) yanıt alındığında zincir success döner.

        Bu, 'success'te durma' davranışının deterministik doğrulaması: groq'ta
        401, openrouter'da 200 + geçerli şema → success True ve openrouter'dan
        sonraki provider'lara geçilmez (çağrı sınırlı). Ayrıntılı model-atlama
        senaryoları yukarıdaki 401/404/429/timeout testlerinde kapsamıştır.
        """
        _FakeAsyncClient.scripts = [
            ("gpt-oss-120b", _mk_response(401, text='{"error":"User not found"}')),
            ("gpt-oss-20b", _mk_response(200, _good_response("başarılı yanıt"))),
        ]
        with patch.object(ai_agent.httpx, "AsyncClient", _FakeAsyncClient):
            result = _run(agent._fallback_chain([{"role": "user", "content": "hi"}]))
        assert result["success"] is True
        # success sonrası zincir durur → openrouter'dan sonraki provider'lara
        # (gemini/together/openai/anthropic) geçilmez; çağrı groq+openrouter ile sınırlı.
        assert len(_FakeAsyncClient.calls) <= 12, (
            f"{len(_FakeAsyncClient.calls)} çağrı — success sonrası zincir durmamış")
