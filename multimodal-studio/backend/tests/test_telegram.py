"""
Telegram bot entegrasyonu testleri
==================================
Gerçek ağ / gerçek token YOK. Tüm Telegram API çağrıları
``httpx.MockTransport`` ile taklit edilir; ajan çağrısı monkeypatch'lenir.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
import pytest

# backend dizinini import yoluna ekle (diğer testlerde olduğu gibi)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import telegram_bot  # noqa: E402

TEST_TOKEN = "123456:TEST-TOKEN-NOT-REAL"


# ---------------------------------------------------------------------------
# Test yardımcıları
# ---------------------------------------------------------------------------

class Recorder:
    """MockTransport isteklerini kaydeder ve sahte yanıtlar üretir."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if "getUpdates" in url:
            return httpx.Response(200, json={"ok": True, "result": []})
        if "sendMessage" in url:
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        if "getMe" in url:
            return httpx.Response(200, json={"ok": True, "result": {"username": "test_bot"}})
        return httpx.Response(200, json={"ok": True, "result": {}})

    def sends(self) -> list[dict]:
        """Gönderilen sendMessage gövdelerini döndürür."""
        out = []
        for req in self.requests:
            if "sendMessage" in str(req.url):
                try:
                    out.append(json.loads(req.content.decode("utf-8")))
                except Exception:
                    out.append({})
        return out


def make_bot(recorder: Recorder, *, allowed=None, default_agent="main-manager"):
    """MockTransport kullanan bir TelegramBot + istemci oluşturur."""
    transport = httpx.MockTransport(recorder.handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.telegram.org")
    bot = telegram_bot.TelegramBot(
        TEST_TOKEN,
        allowed_chat_ids=allowed,
        default_agent_id=default_agent,
        client=client,
    )
    return bot, client


def message_update(chat_id, text, update_id=1):
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    }


def run(coro):
    return asyncio.run(coro)


def fake_chat_factory(captured, *, success=True, response="Merhaba dünya", tools=None):
    async def _fake_chat(message, conversation_id=None, agent_id=None):
        captured["message"] = message
        captured["conversation_id"] = conversation_id
        captured["agent_id"] = agent_id
        captured["calls"] = captured.get("calls", 0) + 1
        return {
            "success": success,
            "response": response,
            "conversation_id": conversation_id or "c1",
            "tools_used": tools or [],
            "iterations": 1,
            "thinking_steps": [],
        }

    return _fake_chat


# ---------------------------------------------------------------------------
# 1) parse_command
# ---------------------------------------------------------------------------

def test_parse_command_agent_with_args():
    assert telegram_bot.parse_command("/agent coder") == ("/agent", "coder")


def test_parse_command_start_without_args():
    assert telegram_bot.parse_command("/start") == ("/start", "")


def test_parse_command_plain_text():
    assert telegram_bot.parse_command("hello") == ("", "hello")


def test_parse_command_new():
    assert telegram_bot.parse_command("/new") == ("/new", "")


def test_parse_command_strips_botname():
    assert telegram_bot.parse_command("/help@TestBot") == ("/help", "")


# ---------------------------------------------------------------------------
# 2) Allowlist
# ---------------------------------------------------------------------------

def test_allowlist_rejects_unauthorized_chat(monkeypatch):
    import ai_agent

    captured = {}
    monkeypatch.setattr(ai_agent, "chat", fake_chat_factory(captured))

    recorder = Recorder()
    bot, client = make_bot(recorder, allowed=[111])

    run(bot._handle_update(message_update(999, "merhaba")))
    run(client.aclose())

    # Ajan çağrılmamalı
    assert captured.get("calls") is None
    # Ama red mesajı gönderilmeli
    sends = recorder.sends()
    assert len(sends) == 1
    assert sends[0]["chat_id"] == 999
    assert "Yetkisiz" in sends[0]["text"]


# ---------------------------------------------------------------------------
# 3) Serbest metin -> ai_agent.chat -> sendMessage
# ---------------------------------------------------------------------------

def test_plain_text_triggers_agent_and_replies(monkeypatch):
    import ai_agent

    captured = {}
    monkeypatch.setattr(
        ai_agent, "chat", fake_chat_factory(captured, response="Merhaba dünya", tools=["x"])
    )

    recorder = Recorder()
    bot, client = make_bot(recorder)

    run(bot._handle_update(message_update(5, "selam")))
    run(client.aclose())

    assert captured["calls"] == 1
    assert captured["message"] == "selam"

    sends = recorder.sends()
    assert len(sends) == 1
    assert sends[0]["chat_id"] == 5
    assert "Merhaba dünya" in sends[0]["text"]
    assert "1 araç" in sends[0]["text"]


def test_failed_agent_result_sends_polite_error(monkeypatch):
    import ai_agent

    captured = {}
    monkeypatch.setattr(
        ai_agent,
        "chat",
        fake_chat_factory(captured, success=False, response="Model hatası"),
    )

    recorder = Recorder()
    bot, client = make_bot(recorder)

    run(bot._handle_update(message_update(6, "test")))
    run(client.aclose())

    sends = recorder.sends()
    assert len(sends) == 1
    assert "Model hatası" in sends[0]["text"]


# ---------------------------------------------------------------------------
# 4) /new ve /agent
# ---------------------------------------------------------------------------

def test_new_changes_conversation_id(monkeypatch):
    recorder = Recorder()
    bot, client = make_bot(recorder)

    run(bot._dispatch(7, "/status"))  # durumu başlat (tg_7_1)
    first = bot._chats[7]["conv_id"]

    run(bot._dispatch(7, "/new"))
    second = bot._chats[7]["conv_id"]

    run(client.aclose())

    assert first == "tg_7_1"
    assert second != first
    assert second.startswith("tg_7_")


def test_reset_behaves_like_new(monkeypatch):
    recorder = Recorder()
    bot, client = make_bot(recorder)

    run(bot._dispatch(8, "/status"))
    first = bot._chats[8]["conv_id"]
    run(bot._dispatch(8, "/reset"))
    second = bot._chats[8]["conv_id"]
    run(client.aclose())

    assert first != second


def test_agent_command_sets_agent(monkeypatch):
    import custom_agents

    monkeypatch.setattr(
        custom_agents,
        "get_agent",
        lambda aid: {"id": aid, "name": "Kod Uzmanı"} if aid == "coder" else None,
    )

    recorder = Recorder()
    bot, client = make_bot(recorder)

    run(bot._dispatch(9, "/agent coder"))
    run(client.aclose())

    assert bot._chats[9]["agent_id"] == "coder"
    assert any("coder" in s["text"] for s in recorder.sends())


def test_agent_command_rejects_unknown(monkeypatch):
    import custom_agents

    monkeypatch.setattr(custom_agents, "get_agent", lambda aid: None)

    recorder = Recorder()
    bot, client = make_bot(recorder)

    run(bot._dispatch(10, "/status"))  # durumu başlat (varsayılan ajan: main-manager)
    assert bot._chats[10]["agent_id"] == "main-manager"

    run(bot._dispatch(10, "/agent bilinmeyen"))
    run(client.aclose())

    # Ajan değişmemeli (varsayılan main-manager)
    assert bot._chats[10]["agent_id"] == "main-manager"
    sends = recorder.sends()
    assert any("bulunamadı" in s["text"] for s in sends)


def test_agent_is_passed_to_ai_agent(monkeypatch):
    import ai_agent
    import custom_agents

    monkeypatch.setattr(
        custom_agents,
        "get_agent",
        lambda aid: {"id": aid, "name": "Kod Uzmanı"} if aid == "coder" else None,
    )
    captured = {}
    monkeypatch.setattr(ai_agent, "chat", fake_chat_factory(captured))

    recorder = Recorder()
    bot, client = make_bot(recorder)

    run(bot._dispatch(11, "/agent coder"))
    run(bot._dispatch(11, "bir fonksiyon yaz"))
    run(client.aclose())

    assert captured["agent_id"] == "coder"


# ---------------------------------------------------------------------------
# 5) send_message parçalama
# ---------------------------------------------------------------------------

def test_send_message_splits_long_text():
    recorder = Recorder()
    bot, client = make_bot(recorder)

    text = "A" * 9000
    run(bot.send_message(1, text))
    run(client.aclose())

    sends = recorder.sends()
    assert len(sends) >= 3
    assert all(len(s["text"]) <= telegram_bot.MAX_MESSAGE_LEN for s in sends)
    assert sum(len(s["text"]) for s in sends) == 9000


def test_split_message_prefers_line_boundaries():
    text = ("satir " * 100 + "\n") * 100  # uzun, çok satırlı
    chunks = telegram_bot.split_message(text, limit=200)
    assert all(len(c) <= 200 for c in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


# ---------------------------------------------------------------------------
# 6) Rotalar (TestClient)
# ---------------------------------------------------------------------------

def _make_app():
    from fastapi import FastAPI
    import telegram_routes

    app = FastAPI()
    app.include_router(telegram_routes.router)
    return app


def test_routes_status_never_leaks_token(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    cfg_file = tmp_path / "telegram_config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "token_enc": "ENCRYPTED-SECRET-VALUE",
                "allowed_chat_ids": [1, 2],
                "enabled": True,
                "default_agent_id": "auto",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(telegram_bot, "CONFIG_FILE", str(cfg_file))
    monkeypatch.setattr(telegram_bot, "_bot", None)

    client = TestClient(_make_app())
    resp = client.get("/api/v1/telegram/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["token_set"] is True
    assert data["allowed_chat_ids"] == [1, 2]
    # Ham/şifreli token yanıtta bulunmamalı
    assert "ENCRYPTED-SECRET-VALUE" not in resp.text
    assert "token" not in {k.lower() for k in data}


def test_routes_send_without_running_bot_is_graceful(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    cfg_file = tmp_path / "telegram_config.json"
    monkeypatch.setattr(telegram_bot, "CONFIG_FILE", str(cfg_file))
    monkeypatch.setattr(telegram_bot, "_bot", None)

    client = TestClient(_make_app())
    resp = client.post("/api/v1/telegram/send", json={"chat_id": 1, "text": "hi"})

    assert resp.status_code in (200, 400)
    body = resp.json()
    if resp.status_code == 200:
        assert body["success"] is False
    else:
        assert "detail" in body


def test_routes_start_without_token_returns_400(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    cfg_file = tmp_path / "telegram_config.json"
    cfg_file.write_text(
        json.dumps({"allowed_chat_ids": [], "enabled": False, "default_agent_id": "auto"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(telegram_bot, "CONFIG_FILE", str(cfg_file))
    monkeypatch.setattr(telegram_bot, "_bot", None)

    client = TestClient(_make_app())
    resp = client.post("/api/v1/telegram/start")

    assert resp.status_code == 400
    assert "detail" in resp.json()


# ---------------------------------------------------------------------------
# Ek: ayar dosyası şifreleme davranışı (hermetik, tmp_path)
# ---------------------------------------------------------------------------

def test_save_config_encrypts_token_and_load_hides_raw(monkeypatch, tmp_path):
    cfg_file = tmp_path / "telegram_config.json"
    monkeypatch.setattr(telegram_bot, "CONFIG_FILE", str(cfg_file))

    saved = telegram_bot.save_config(
        {
            "token": "123456:ABC-DEF",
            "allowed_chat_ids": [42],
            "enabled": False,
            "default_agent_id": "auto",
        }
    )

    # Şifreleme mümkünse token_enc, değilse düz token alanı olur.
    assert saved.get("token_enc") or saved.get("token")
    raw_on_disk = cfg_file.read_text(encoding="utf-8")
    # Düz metin token diskte bulunmamalı (şifreleme başarılıysa)
    if saved.get("token_enc"):
        assert "123456:ABC-DEF" not in raw_on_disk

    loaded = telegram_bot.load_config()
    assert loaded["allowed_chat_ids"] == [42]
    assert telegram_bot.token_is_set() is True

    # status() token içermez
    bot = telegram_bot.TelegramBot("secret-token")
    st = bot.status()
    assert "token" not in st
    assert "secret-token" not in json.dumps(st)
