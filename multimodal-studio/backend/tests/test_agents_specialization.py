"""
Tests for Agent Specialization, Dynamic Prompting, and Auto-Routing
===================================================================
AŞAMA 3, 4, 5, 6 ve 7 testleri:
- 20 ajanın uzmanlık alanları ve araç uyumu
- Analyst, Designer, Researcher ve Assistant için geliştirilmiş araçlar
- auto_select_agent gelişmiş anahtar kelime yönlendirmesi
- ai_agent.chat() dinamik prompt oluşturma (araç uyumsuzluğu koruması)
- ai_agent.chat() agent_id='auto' otomatik uzman seçimi
- custom_agent_routes /tools/available tam araç kapsamı
- Telegram botu /agents zengin liste ve auto yönlendirme
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import custom_agents as ca
import custom_agent_routes as car
import tools_spec


def test_roster_integrity_and_specialization():
    """Tüm 20 ajanın varlığı, temel alanları ve araç atamaları."""
    agents = ca.load_agents()
    assert len(agents) == 20
    by_id = {a["id"]: a for a in agents}

    # Özel araç atamaları doğrulaması
    assert "generate_image" in by_id["designer"]["tools"], "Designer gerçek görsel üretebilmeli"
    assert "calculate" in by_id["analyst"]["tools"], "Analyst hesaplama yapabilmeli"
    assert "calculate" in by_id["coder"]["tools"], "Coder hesaplama yapabilmeli"
    assert "calculate" in by_id["teacher"]["tools"], "Teacher hesaplama yapabilmeli"
    assert "rag_search" in by_id["researcher"]["tools"], "Researcher RAG araması yapabilmeli"
    assert "rag_list_documents" in by_id["researcher"]["tools"], "Researcher belgeleri listeleyebilmeli"
    assert "calculate" in by_id["assistant"]["tools"], "Genel asistan hesaplama yapabilmeli"
    assert "generate_image" in by_id["assistant"]["tools"], "Genel asistan görsel üretebilmeli"
    assert "rag_search" in by_id["assistant"]["tools"], "Genel asistan RAG araması yapabilmeli"

    # Her ajanın geçerli araçlara sahip olduğu ve prompt uzunluğu
    all_spec_tools = {t["function"]["name"] for t in tools_spec.TOOLS}
    for a in agents:
        assert a["id"], "Ajan ID'si boş olamaz"
        assert a["name"], "Ajan adı boş olamaz"
        assert a["icon"], "Ajan ikonu bulunmalı"
        assert a["system_prompt"] and len(a["system_prompt"]) > 100
        assert a["tools"], f"{a['id']} ajanı en az bir araca sahip olmalı"
        # Tanımsız araç atanmadığını doğrula
        invalid = set(a["tools"]) - all_spec_tools
        assert not invalid, f"{a['id']} geçersiz araçlar içeriyor: {invalid}"


def test_auto_select_agent_enhanced():
    """Geliştirilmiş anahtar kelimelerle doğru uzmana yönlendirme."""
    # Matematik/istatistik -> analyst
    assert ca.auto_select_agent("Bana bu tablonun ortalamasını ve varyansını hesapla") == "analyst"
    # RAG / Belge araştırma -> researcher
    assert ca.auto_select_agent("Doküman arşivinde literatür ve kaynakça araştırması yap") == "researcher"
    # Siber güvenlik -> security
    assert ca.auto_select_agent("Bu sistemdeki cve zafiyetlerini ve sızma açıklarını denetle") == "security"
    # Python -> python-pro
    assert ca.auto_select_agent("python ile bir pytest testi yaz") == "python-pro"
    # Frontend -> frontend-pro
    assert ca.auto_select_agent("responsive bir react componenti tasarla") in ("frontend-pro", "designer")
    # Video -> video-pro
    assert ca.auto_select_agent("bana mp4 video üret") == "video-pro"
    # Görsel -> image-pro
    assert ca.auto_select_agent("görsel üret, illüstrasyon çiz") == "image-pro"


def test_tools_available_endpoint():
    """API'nin kullanılabilir araçlar listesinde tüm kritik araçların yer alması."""
    app = FastAPI()
    app.include_router(car.router)
    client = TestClient(app)

    r = client.get("/api/v1/agents/tools/available")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    tool_ids = {t["id"] for t in data["tools"]}

    for expected in ["generate_image", "calculate", "rag_search", "rag_add_document", "rag_list_documents"]:
        assert expected in tool_ids, f"{expected} kullanılabilir araçlar listesinde bulunmalı"


@pytest.mark.asyncio
async def test_ai_agent_dynamic_tool_prompting():
    """Dinamik sistem promptunun sadece ajana tahsisli araçları içermesi (araç uyumsuzluğu koruması)."""
    import ai_agent

    # chat-pro ajanı (sadece sohbet ve okuma araçları var; execute_command YOK)
    chat_agent = ca.get_agent("chat-pro")
    assert chat_agent is not None
    assert "execute_command" not in chat_agent["tools"]

    # TrueAIAgent sınıfının prompt yapılandırmasını test et
    agent_inst = ai_agent.get_agent_v6()
    try:
        # Chat çağrısını taklit eden yapay bir çağrıyla prompt içeriğini kontrol et
        # _tools_payload() chat-pro için sadece onun araçlarını dönmeli
        agent_inst._active_tools = chat_agent["tools"]
        payload_tool_names = {t["function"]["name"] for t in agent_inst._tools_payload()}
        assert payload_tool_names == set(chat_agent["tools"])
        assert "execute_command" not in payload_tool_names
        assert "generate_real_video" not in payload_tool_names
    finally:
        agent_inst._active_tools = None


@pytest.mark.asyncio
async def test_ai_agent_auto_routing(monkeypatch):
    """ai_agent.chat(agent_id='auto') çağrısının otomatik uzmana delege etmesi."""
    import ai_agent

    captured = {}

    async def fake_call_llm(self, messages):
        # İlk mesaj system mesajı
        captured["system"] = messages[0]["content"] if messages else ""
        return {
            "success": True,
            "data": {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "Analiz tamamlandı.",
                        "tool_calls": None
                    }
                }]
            }
        }

    monkeypatch.setattr(ai_agent.NexusAIAgent, "_call_llm", fake_call_llm)
    agent_inst = ai_agent.get_agent_v6()

    res = await agent_inst.chat("Bana bu verinin ortalamasını hesapla", agent_id="auto")
    assert res["success"] is True
    # Analyst ajanının promptunun seçildiğini doğrula
    assert "Sen veri analizi uzmanısın" in captured["system"] or "calculate" in captured["system"]


def test_telegram_bot_agents_listing_and_auto():
    """Telegram botunun zengin /agents listesi ve auto desteği."""
    import telegram_bot
    from tests.test_telegram import Recorder, make_bot, run

    recorder = Recorder()
    bot, client = make_bot(recorder)

    # /agents komutu
    run(bot._dispatch(101, "/agents"))
    sends = recorder.sends()
    assert len(sends) == 1
    assert "Kullanılabilir Ajanlar" in sends[0]["text"]
    assert "Otomatik seçim için: /agent auto" in sends[0]["text"]

    # /agent auto komutu
    run(bot._dispatch(101, "/agent auto"))
    assert bot._chats[101]["agent_id"] == "auto"

    run(client.aclose())
