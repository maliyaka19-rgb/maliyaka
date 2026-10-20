"""
Tests for Agent Specialization, Dynamic Prompting, and Auto-Routing
===================================================================
AŞAMA 3, 4, 5, 6 ve 7 testleri:
- 22 ajanlık resmî kadro (Ana Yönetici + Kodlama Yöneticisi + 20 uzman)
- Uzmanların araç uyumu ve silinen ajanların geri gelmemesi
- Eski anahtar kelimelerin resmî ajana yönlendirilmesi
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
    """Resmî kadro: Ana Yönetici + Kodlama Yöneticisi + 20 uzman (toplam 22)."""
    agents = ca.load_agents()
    assert len(agents) == 22
    by_id = {a["id"]: a for a in agents}
    expected_ids = ["main-manager", "coding-manager"] + [
        s["id"] for s in ca.CODING_SPECIALISTS
    ]
    assert [a["id"] for a in agents] == expected_ids
    assert set(by_id) == ca.OFFICIAL_AGENT_IDS
    assert not (set(by_id) & ca.REMOVED_AGENT_IDS), "silinen ajan kadroya geri dondu"

    # Adlar kullanıcı tanımıyla birebir aynı olmalı.
    for agent_id, name in ca.OFFICIAL_AGENT_NAMES.items():
        assert by_id[agent_id]["name"] == name

    # Uzmanlık araçları: yazma/çalıştırma yetkisi dar tutulmalı.
    assert "write_file" in by_id["frontend-pro"]["tools"]
    assert "execute_command" in by_id["coder"]["tools"]
    assert "execute_command" not in by_id["code-analyst"]["tools"]
    assert "web_search" in by_id["security"]["tools"]

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


def test_keyword_select_agent_enhanced():
    """Eski anahtar kelimeler resmî kadrodaki en yakın ajana yönlenir."""
    assert ca.keyword_select_agent("Bana bu tablonun ortalamasını ve varyansını hesapla") == "code-analyst"
    assert ca.keyword_select_agent("Doküman arşivinde literatür ve kaynakça araştırması yap") == "architect"
    assert ca.keyword_select_agent("Bu sistemdeki cve zafiyetlerini ve sızma açıklarını denetle") == "security"
    assert ca.keyword_select_agent("python ile bir pytest testi yaz") == "coder"
    assert ca.keyword_select_agent("responsive bir react componenti tasarla") == "frontend-pro"
    assert ca.keyword_select_agent("bana mp4 video üret") == "main-manager"
    assert ca.keyword_select_agent("görsel üret, illüstrasyon çiz") == "main-manager"
    assert ca.keyword_select_agent("ekip olarak hepsini yap, komple site") == "coding-manager"
    assert ca.keyword_select_agent("bu kodu denetle, hata var mı?") == "reviewer"

    for message in ["merhaba", "video üret", "python script yaz", "bilmiyorum"]:
        assert ca.keyword_select_agent(message) in ca.OFFICIAL_AGENT_IDS


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

    # code-analyst ajanı (sadece okuma/analiz araçları var; execute_command YOK)
    narrow_agent = ca.get_agent("code-analyst")
    assert narrow_agent is not None
    assert "execute_command" not in narrow_agent["tools"]

    # TrueAIAgent sınıfının prompt yapılandırmasını test et
    agent_inst = ai_agent.get_agent_v6()
    try:
        # Chat çağrısını taklit eden yapay bir çağrıyla prompt içeriğini kontrol et
        # _tools_payload() code-analyst için sadece onun araçlarını dönmeli
        agent_inst._active_tools = narrow_agent["tools"]
        payload_tool_names = {t["function"]["name"] for t in agent_inst._tools_payload()}
        assert payload_tool_names == set(narrow_agent["tools"])
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
    # Otomatik seçim artık DAİMA Ana Yönetici Ajan'a gider (D-043).
    assert "ANA YÖNETİCİ AJANIsın" in captured["system"]


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
