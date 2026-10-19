"""Tests for the expanded pro-agent roster + team pipeline (Oturum 11)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import custom_agents as ca
import custom_agent_routes as car


def test_default_roster_keeps_original_20_unique_agents():
    """Mevcut 20 genel ajan KORUNMALI; kodlama ekibi EKLENEBİLİR (silinemez)."""
    ids = [a["id"] for a in ca.DEFAULT_AGENTS]
    assert len(ids) == len(set(ids))          # benzersiz
    assert len(ids) >= 20
    original = ["assistant", "coder", "teacher", "designer", "analyst", "artist",
                "researcher", "writer", "translator", "marketer", "devops", "security",
                "chat-pro", "python-pro", "frontend-pro", "backend-pro",
                "image-pro", "video-pro", "reviewer", "team-lead"]
    for must in original:
        assert must in ids, f"Mevcut ajan silinmis: {must}"


def test_new_agents_have_narrow_toolboxes():
    by_id = {a["id"]: a for a in ca.DEFAULT_AGENTS}
    assert "generate_image" in by_id["image-pro"]["tools"]
    assert "generate_real_video" in by_id["video-pro"]["tools"]
    assert "generate_image" not in by_id["video-pro"]["tools"]
    assert "execute_command" in by_id["python-pro"]["tools"]
    assert "execute_command" not in by_id["chat-pro"]["tools"]
    for a in ca.DEFAULT_AGENTS:
        assert a["system_prompt"] and len(a["system_prompt"]) > 100
        assert a["tools"]  # no agent left tool-less


def test_auto_select_routes_to_specialists():
    assert ca.auto_select_agent("python ile bir script yaz") == "python-pro"
    assert ca.auto_select_agent("bana bir video üret, mp4 olsun") == "video-pro"
    assert ca.auto_select_agent("görsel üret, illüstrasyon yap") == "image-pro"
    assert ca.auto_select_agent("bu kodu denetle, hata var mı?") == "reviewer"
    assert ca.auto_select_agent("ekip olarak hepsini yap, komple site") == "team-lead"


def _team_client(monkeypatch):
    async def fake_chat(message, conversation_id=None, history=None, agent_id=None):
        return {"success": True, "response": f"[{agent_id}] {message[:40]}",
                "conversation_id": conversation_id or "c1",
                "tools_used": [], "thinking_steps": []}
    import ai_agent
    monkeypatch.setattr(ai_agent, "chat", fake_chat)
    app = FastAPI()
    app.include_router(car.router)
    return TestClient(app)


def test_team_run_pipeline(monkeypatch):
    client = _team_client(monkeypatch)
    r = client.post("/api/v1/agents/team/run",
                    json={"message": "python ile bir script yaz", "refine": True})
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["specialist"]["id"] == "python-pro"
    assert data["stages"]["draft"]["agent_id"] == "python-pro"
    assert data["stages"]["review"]["agent_id"] == "reviewer"
    assert "[team-lead]" in data["response"]


def test_team_run_without_refine(monkeypatch):
    client = _team_client(monkeypatch)
    r = client.post("/api/v1/agents/team/run",
                    json={"message": "merhaba", "refine": False})
    assert r.status_code == 200
    assert r.json()["success"] is True
