"""
Kodlama ekibi kadrosu: Ana Yönetici -> Kodlama Yöneticisi -> 20 uzman.

Doğrulanan sözleşme:
  * 20 uzmanın tamamı kayıtlı ajan olarak vardır (eksik sessizce yutulmaz).
  * Hiyerarşi grupları kullanıcı tanımıyla birebir aynıdır (4 / 6 / 5 / 5).
  * Görev türleri ilgili uzmanı GERÇEKTEN akışa koyar (frontend/database/devops).
  * Öğrenme içgörüleri `learning-agent` tarafından üretilir.
  * Varsayılan akış Ana Yönetici raporundan geçer.
"""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ai_agent
import coding_insights as cins
import coding_manager as cm
import coding_routes as cr
import custom_agent_routes as car
from custom_agents import CODING_SPECIALISTS, CODING_TEAM_GROUPS, coding_hierarchy, load_agents


@pytest.fixture(autouse=True)
def _isolate_agents_file(monkeypatch, tmp_path):
    """Testler gerçek ajan dosyasını yazmasın (hermetik test kuralı)."""
    import custom_agents

    monkeypatch.setattr(custom_agents, "AGENTS_FILE", str(tmp_path / "agents.json"))


def test_roster_has_20_unique_registered_specialists():
    assert len(CODING_SPECIALISTS) == 20
    ids = [s["id"] for s in CODING_SPECIALISTS]
    assert len(ids) == len(set(ids)), "aynı ajan iki kez kadroda olamaz"

    agents = {a["id"] for a in load_agents()}
    assert not (set(ids) - agents), f"kayıtlı olmayan uzman: {set(ids) - agents}"


def test_roster_group_sizes_match_user_definition():
    counts = {g: sum(1 for s in CODING_SPECIALISTS if s["group"] == g) for g in CODING_TEAM_GROUPS}
    assert counts == {
        "A. Analiz ve planlama": 4,
        "B. Yazılım geliştirme": 6,
        "C. Kalite ve güvenlik": 5,
        "D. Yayın ve sürekli geliştirme": 5,
    }


def test_hierarchy_endpoint_exposes_managers_and_20_specialists():
    app = FastAPI()
    app.include_router(car.router)
    client = TestClient(app)

    r = client.get("/api/v1/agents/hierarchy")

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is True
    assert data["main_manager"]["id"] == "main-manager"
    assert data["coding_manager"]["id"] == "coding-manager"
    assert data["total_specialists"] == 20
    assert data["missing"] == []

    ids = [s["id"] for g in data["groups"] for s in g["specialists"]]
    assert len(ids) == 20
    assert ids == [s["id"] for s in CODING_SPECIALISTS]


def test_hierarchy_is_deterministic():
    a = coding_hierarchy()
    b = coding_hierarchy()
    assert a == b


@pytest.mark.parametrize("message,expected", [
    ("arayüz bileşeni ekle", cm.TaskType.FRONTEND),
    ("veritabanı şemasına tablo ekle", cm.TaskType.DATABASE),
    ("docker ile deploy et", cm.TaskType.DEVOPS),
    ("api endpoint ekle", cm.TaskType.API),
])
def test_task_type_routing(message, expected):
    assert cm.classify_task(message) == expected


def test_workflows_route_to_the_right_specialist():
    assert cm.WORKFLOWS[cm.TaskType.FEATURE][0]["role"] == "task-planner"

    frontend = [s["role"] for s in cm.WORKFLOWS[cm.TaskType.FRONTEND]]
    assert "frontend-pro" in frontend

    db_writers = [s["role"] for s in cm.WORKFLOWS[cm.TaskType.DATABASE] if s.get("write")]
    assert "database-pro" in db_writers

    devops = [s["role"] for s in cm.WORKFLOWS[cm.TaskType.DEVOPS]]
    assert "devops" in devops

    api = [s["role"] for s in cm.WORKFLOWS[cm.TaskType.API]]
    assert "database-pro" in api


def test_all_specialists_are_reachable_somewhere():
    """Kadrodaki her uzman en az bir iş akışında görev almalı (kâğıt üstünde kalmasın)."""
    routed = {s["role"] for steps in cm.WORKFLOWS.values() for s in steps}
    unused = {s["id"] for s in CODING_SPECIALISTS} - routed
    # learning-agent LLM adımı değil, görev sonrası otomatik içgörü katmanıdır.
    assert unused <= {"learning-agent"}, unused
    assert "learning-agent" in {s["id"] for s in CODING_SPECIALISTS}


def test_insights_are_attributed_to_learning_agent():
    ins = cins._make_insight("kanitsiz", "uyari", "f", {}, "r", "k")
    assert ins["agent"] == "learning-agent"
    assert ins["applied"] is False


def test_keyword_selector_kept_as_fallback():
    import custom_agents as ca

    assert ca.keyword_select_agent("bana mp4 video üret") == "main-manager"


def test_coding_detection_for_manager_delegation():
    from ai_agent_routes import _is_coding_task

    assert _is_coding_task("python kodumda hata var, düzelt") is True
    assert _is_coding_task("arayüz bileşeni ekle") is True
    assert _is_coding_task("merhaba, nasılsın?") is False


def test_main_manager_chat_delegates_coding_to_chain(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import ai_agent_routes as ar

    called = {}

    async def fake_run(self, message, mode="plan", conversation_id=None,
                       via_main_manager=True, **kwargs):
        called.update(message=message, mode=mode, via_main_manager=via_main_manager)
        return {
            "success": True,
            "final_answer": "Zincir sonucu",
            "conversation_id": conversation_id,
            "task_id": "t1",
            "task_type": "frontend",
            "mode": "plan",
            "report": {"3_kullanilan_uzmanlar": ["code-analyst", "frontend-pro"]},
        }

    monkeypatch.setattr(cm.CodingTaskManager, "run", fake_run)

    app = FastAPI()
    app.include_router(ar.router)
    client = TestClient(app)

    r = client.post("/api/v1/ai/chat", json={"message": "arayüz bileşeni ekle", "agent_id": "main-manager"})

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is True
    assert data["response"] == "Zincir sonucu"
    assert data["coding"] == {
        "task_id": "t1", "task_type": "frontend", "mode": "plan",
        "experts": ["code-analyst", "frontend-pro"],
    }
    assert called == {"message": "arayüz bileşeni ekle", "mode": "plan", "via_main_manager": True}


def test_legacy_auto_chat_general_message_stays_single_agent(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import ai_agent_routes as ar

    async def fail_run(*args, **kwargs):
        raise AssertionError("genel sohbet zinciri çalıştırmamalı")

    seen = {}

    async def fake_chat(message, conversation_id=None, history=None, agent_id=None):
        seen["agent_id"] = agent_id
        return {"success": True, "response": "selam", "conversation_id": conversation_id or "c",
                "tools_used": [], "thinking_steps": []}

    monkeypatch.setattr(cm.CodingTaskManager, "run", fail_run)
    monkeypatch.setattr(ar, "chat", fake_chat)

    app = FastAPI()
    app.include_router(ar.router)
    client = TestClient(app)

    r = client.post("/api/v1/ai/chat", json={"message": "merhaba, nasılsın?", "agent_id": "auto"})

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["response"] == "selam"
    assert seen["agent_id"] == "main-manager"


def test_main_manager_is_default_and_reviews_report(monkeypatch, tmp_path):
    assert cr.CodingRunRequest(message="x").via_main_manager is True

    monkeypatch.setattr(cm, "TASKS_FILE", str(tmp_path / "tasks.json"))
    calls = []

    async def fake_chat(message, conversation_id=None, history=None, agent_id=None,
                        tools_override=None, system_prefix=None):
        calls.append(agent_id)
        return {
            "success": True,
            "response": f"[{agent_id}] tamam",
            "conversation_id": conversation_id or "c",
            "tools_used": [],
            "files_changed": [],
            "thinking_steps": [],
        }

    monkeypatch.setattr(ai_agent, "chat", fake_chat)

    res = asyncio.run(cm.CodingTaskManager().run("arayüz bileşeni ekle", mode="plan"))

    assert res["task_type"] == "frontend"
    assert calls[0] == "main-manager", "akış Ana Yönetici intake ile başlamalı"
    assert calls[-1] == "main-manager", "nihai yanıt Ana Yönetici'den gelmeli"
    assert res["report"]["3_kullanilan_uzmanlar"][-1] in ("reviewer", "regression-tester")
    assert "reviewer" in res["report"]["3_kullanilan_uzmanlar"]
    assert res["final_answer"] == "[main-manager] tamam"


def test_execute_mode_prompt_demands_real_write_file(monkeypatch, tmp_path):
    """UYGULA modunda ajan kodu metne dökmemeli; write_file çağırmalı."""
    captured = {}

    async def fake_chat(message, conversation_id=None, history=None, agent_id=None,
                        tools_override=None, system_prefix=None):
        captured["tools"] = tools_override
        captured["prefix"] = system_prefix
        return {"success": True, "response": "ok", "files_changed": ["index.html"],
                "tools_used": ["write_file"], "thinking_steps": []}

    monkeypatch.setattr(ai_agent, "chat", fake_chat)

    mgr = cm.CodingTaskManager(working_dir=str(tmp_path))
    step = {"role": "frontend-pro", "goal": "siteyi yaz", "write": True}

    msg = asyncio.run(mgr._run_step("t1", "conv", 0, step, "execute", "yemek sitesi yap"))

    assert "write_file" in captured["prefix"]
    assert "generate_code dosyaya YAZMAZ" in captured["prefix"]
    assert "write_file" in (captured["tools"] or [])
    assert "generate_code" not in (captured["tools"] or [])
    assert msg.changes == ["index.html"]
