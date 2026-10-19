"""
Yerel Model Yedekliligi (local_llm) testleri.

Test edilen davranislar:
  * tespit: GERCEK, calisan bir yerel OpenAI-uyumlu HTTP sunucusuna karsi
  * tespit: hicbir sey dinlemiyorken guvenli donus (istisna yok)
  * chat(): gercek yerel sunucuya karsi uctan uca (model otomatik secimi dahil)
  * GUVENLIK: loopback olmayan adres reddedilir; varsayilan KAPALI
  * entegrasyon: `_fallback_chain` bulut saglayicisi yokken yerel yedegi kullanir
  * entegrasyon: kapaliyken yerel yol HIC cagrilmaz (davranis degismez)
  * rota: GET /api/v1/models/local/status

Sunucu gercektir (threaded http.server, 127.0.0.1, rastgele port); dis ag YOK.
"""
import asyncio
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ai_agent
import local_llm
import model_routes


# ---------------------------------------------------------------- gercek yerel sunucu

class _Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/v1/models"):
            self._send(200, {"object": "list", "data": [{"id": "test-local-model"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/").endswith("/v1/chat/completions"):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            self._send(200, {"choices": [{"message": {"role": "assistant",
                                                      "content": "YEREL YANIT"}}]})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *args):  # testleri kirletmesin
        pass


@pytest.fixture
def local_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}/v1"
    finally:
        srv.shutdown()
        srv.server_close()


def _closed_port_url() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/v1"


def _bare_agent():
    agent = ai_agent.NexusAIAgent.__new__(ai_agent.NexusAIAgent)
    agent.llm_config = SimpleNamespace(api_key="", base_url="", model="",
                                       temperature=0.7, max_tokens=512)
    agent.provider = "groq"
    return agent


# ---------------------------------------------------------------- tespit

def test_detect_finds_running_local_server(local_server, monkeypatch):
    monkeypatch.setenv(local_llm.ENV_URL, local_server)
    info = asyncio.run(local_llm.detect())
    assert info["available"] is True
    assert info["runtime"] == "env"
    assert "test-local-model" in info["models"]


def test_detect_is_safe_when_nothing_listens(monkeypatch):
    monkeypatch.setenv(local_llm.ENV_URL, _closed_port_url())
    info = asyncio.run(local_llm.detect(timeout=0.5))
    assert info["available"] is False
    assert info["models"] == []
    assert info["checked"], "denenen adresler raporlanmali"


# ---------------------------------------------------------------- chat

def test_chat_end_to_end_with_real_local_server(local_server, monkeypatch):
    monkeypatch.delenv(local_llm.ENV_MODEL, raising=False)
    monkeypatch.setenv(local_llm.ENV_URL, local_server)
    res = asyncio.run(local_llm.chat([{"role": "user", "content": "merhaba"}]))
    assert res["success"] is True
    assert res["provider"] == "local"
    assert res["model"] == "test-local-model"  # model verilmedi -> otomatik secildi
    assert res["data"]["choices"][0]["message"]["content"] == "YEREL YANIT"


def test_chat_rejects_non_loopback(monkeypatch):
    monkeypatch.setenv(local_llm.ENV_URL, "http://example.com/v1")
    res = asyncio.run(local_llm.chat([{"role": "user", "content": "x"}]))
    assert res["success"] is False
    assert "localhost" in res["error"]


def test_is_enabled_env_semantics(monkeypatch):
    monkeypatch.delenv(local_llm.ENV_URL, raising=False)
    assert local_llm.is_enabled() is False, "varsayilan KAPALI olmali"

    monkeypatch.setenv(local_llm.ENV_URL, "http://127.0.0.1:11434/v1")
    assert local_llm.is_enabled() is True

    monkeypatch.setenv(local_llm.ENV_URL, "http://evil.example.com/v1")
    assert local_llm.is_enabled() is False, "loopback olmayan adres etkin olamaz"


# ---------------------------------------------------------------- entegrasyon

def test_fallback_chain_uses_local_when_no_cloud_provider(local_server, monkeypatch):
    monkeypatch.setenv(local_llm.ENV_URL, local_server)
    monkeypatch.setattr(model_routes, "MODEL_CATALOG", {})
    monkeypatch.setattr(model_routes, "_load_config", lambda: {"api_keys": {}})

    agent = _bare_agent()
    result = asyncio.run(agent._fallback_chain([{"role": "user", "content": "merhaba"}]))

    assert result["success"] is True
    assert result.get("local") is True
    assert result["data"]["choices"][0]["message"]["content"] == "YEREL YANIT"


def test_fallback_chain_skips_local_when_disabled(monkeypatch):
    monkeypatch.delenv(local_llm.ENV_URL, raising=False)
    monkeypatch.setattr(model_routes, "MODEL_CATALOG", {})
    monkeypatch.setattr(model_routes, "_load_config", lambda: {"api_keys": {}})

    calls = []
    monkeypatch.setattr(local_llm, "chat", lambda *a, **k: calls.append("chat"))

    agent = _bare_agent()

    async def fake_fallback_response(messages):
        return {"success": True, "data": {"choices": [
            {"message": {"role": "assistant", "content": "kural-tabanli"}}]}}

    agent._fallback_response = fake_fallback_response

    result = asyncio.run(agent._fallback_chain([{"role": "user", "content": "merhaba"}]))

    assert calls == [], "yerel model kapaliyken cagrilmamali"
    assert result["data"]["choices"][0]["message"]["content"] == "kural-tabanli"


# ---------------------------------------------------------------- rota

def test_local_status_route(monkeypatch):
    monkeypatch.delenv(local_llm.ENV_URL, raising=False)
    app = FastAPI()
    app.include_router(model_routes.router)
    client = TestClient(app)

    resp = client.get("/api/v1/models/local/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "available" in body
    assert body["enabled"] is False
    assert "how_to_enable" in body
