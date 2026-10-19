"""
Kodlama Yöneticisi (Coding Manager) — gerçek testler.

Test edilen davranışlar:
  * görev sınıflandırma
  * görev türü -> uzman iş akışı seçimi ve rol mevcudiyeti
  * adım-bazlı EN AZ YETKİ (plan modunda yazma araçları verilmez)
  * dosya çakışma kilidi
  * 11 alanlı yapılandırılmış rapor
  * uçtan uca boru hattı (Ana Yönetici -> Kodlama Yöneticisi -> uzmanlar -> rapor)
  * execute modu için onay zorunluluğu
  * başarısız doğrulamada sınırlı yeniden deneme
  * ajan çökmesinin sessizce kaybolmaması
  * bağımsız analiz adımlarının paralel çalışması
  * HTTP rotaları
"""
import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ai_agent
import coding_manager as cm
import coding_routes as cr


# ---------------------------------------------------------------- yardımcı

def _fake_chat_factory(calls, delay=0.0, fail_roles=()):
    async def fake_chat(message, conversation_id=None, history=None, agent_id=None,
                        tools_override=None, system_prefix=None):
        calls.append({"agent_id": agent_id, "tools": tools_override,
                      "msg": message, "prefix": system_prefix})
        if delay:
            await asyncio.sleep(delay)
        if agent_id in fail_roles:
            return {"success": False, "error": "sentetik ajan hatası",
                    "conversation_id": conversation_id or "c"}
        return {"success": True, "response": f"[{agent_id}] tamam",
                "conversation_id": conversation_id or "c",
                "tools_used": ["execute_command"] if agent_id == "test-engineer" else [],
                "thinking_steps": []}
    return fake_chat


def _tmp_tasks(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "TASKS_FILE", str(tmp_path / "coding_tasks.json"))


# ---------------------------------------------------------------- birim

def test_classify_task_types():
    assert cm.classify_task("bu fonksiyonda XSS güvenlik açığı var") == cm.TaskType.SECURITY
    assert cm.classify_task("login hata veriyor, çalışmıyor") == cm.TaskType.BUGFIX
    assert cm.classify_task("sayfa çok yavaş, performans düşük") == cm.TaskType.PERFORMANCE
    assert cm.classify_task("yeni bir REST api endpoint ekle") == cm.TaskType.API
    assert cm.classify_task("bu kodu refactor et, tekrarları temizle") == cm.TaskType.REFACTOR
    assert cm.classify_task("yeni özellik ekle: dışa aktarma") == cm.TaskType.FEATURE
    assert cm.classify_task("hangi kütüphane daha iyi, araştır") == cm.TaskType.RESEARCH
    assert cm.classify_task("selam") == cm.TaskType.GENERAL


def test_all_workflow_roles_exist_as_agents():
    from custom_agents import load_agents
    ids = {a["id"] for a in load_agents()}
    roles = {s["role"] for steps in cm.WORKFLOWS.values() for s in steps}
    missing = roles - ids
    assert not missing, f"Tanımsız rol(ler): {missing}"


def test_workflows_cover_every_task_type():
    for t in cm.TaskType:
        assert t in cm.WORKFLOWS
        assert cm.WORKFLOWS[t], f"Boş iş akışı: {t}"


def test_select_workflow_returns_defensive_copy():
    a = cm.select_workflow(cm.TaskType.FEATURE)
    a[0]["role"] = "MUTATED"
    b = cm.select_workflow(cm.TaskType.FEATURE)
    assert b[0]["role"] != "MUTATED"


def test_resolve_tools_least_privilege():
    coder = {"tools": ["read_file", "write_file", "execute_command", "web_search"]}
    write_step = {"write": True}
    read_step = {"write": False}

    # plan modunda YAZMA adımı bile yalnızca salt-okuma araçları alır
    plan_tools = cm.CodingTaskManager.resolve_tools(coder, write_step, "plan")
    assert "write_file" not in plan_tools
    assert "execute_command" not in plan_tools
    assert set(plan_tools) <= cm.READ_ONLY_SET

    # execute modunda yazma adımı tanımlı araçlarını alır
    exec_tools = cm.CodingTaskManager.resolve_tools(coder, write_step, "execute")
    assert "write_file" in exec_tools

    # execute modunda bile salt-okuma adımı yazma aracı almaz
    ro = cm.CodingTaskManager.resolve_tools(coder, read_step, "execute")
    assert "write_file" not in ro


def test_file_lock_registry_prevents_conflict():
    reg = cm.FileLockRegistry()
    assert reg.acquire("backend/app.py", "coder") is True
    assert reg.acquire("backend/app.py", "bug-fixer") is False
    assert reg.owner("backend/app.py") == "coder"
    reg.release("backend/app.py", "coder")
    assert reg.acquire("backend/app.py", "bug-fixer") is True
    assert reg.conflicts and reg.conflicts[0]["owner"] == "bug-fixer"


def test_build_report_has_11_fields():
    record = {"task_id": "t1", "request": "örnek", "mode": "plan",
              "tools_used": [], "remaining_issues": [], "verification": {}}
    report = cm.CodingTaskManager.build_report(record, [], cm.TaskType.GENERAL)
    for i in range(1, 12):
        key = next((k for k in report if k.startswith(f"{i}_")), None)
        assert key is not None, f"Rapor alanı {i} eksik"


# ---------------------------------------------------------------- boru hattı

def test_run_plan_mode_pipeline(monkeypatch, tmp_path):
    _tmp_tasks(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(ai_agent, "chat", _fake_chat_factory(calls))

    mgr = cm.CodingTaskManager()
    result = asyncio.run(mgr.run("login hatası var, düzelt", mode="plan"))

    # görev türü ve akış
    assert result["task_type"] == "bugfix"
    steps = cm.select_workflow(cm.TaskType.BUGFIX)
    expected_roles = [s["role"] for s in steps]

    # rapor uzmanları doğru sırada
    assert result["report"]["3_kullanilan_uzmanlar"] == expected_roles

    # Ana Yönetici devrede (intake + review)
    mm_calls = [c for c in calls if c["agent_id"] == "main-manager"]
    assert len(mm_calls) == 2

    # PLAN modunda hiçbir adıma yazma aracı verilmemiş olmalı
    for c in calls:
        if c["tools"] is not None:
            assert "write_file" not in c["tools"], c
            assert "edit_file" not in c["tools"], c

    # rapor anahtarları
    assert result["report"]["1_gorev_kimligi"]["gorev_turu"] == "bugfix"
    assert result["status"] == "tamamlandi"

    # kalıcı kayıt
    assert cm.get_task(result["task_id"]) is not None


def test_execute_requires_confirmation(monkeypatch, tmp_path):
    _tmp_tasks(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(ai_agent, "chat", _fake_chat_factory(calls))
    mgr = cm.CodingTaskManager()
    result = asyncio.run(mgr.run("yeni özellik ekle", mode="execute", confirm=False,
                                 via_main_manager=False))
    assert result["mode"] == "plan", "Onaysız execute plan moduna düşürülmeliydi"


def test_execute_with_confirmation_grants_write(monkeypatch, tmp_path):
    _tmp_tasks(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(ai_agent, "chat", _fake_chat_factory(calls))
    mgr = cm.CodingTaskManager()
    result = asyncio.run(mgr.run("yeni özellik ekle: dışa aktarma",
                                 mode="execute", confirm=True, via_main_manager=False))
    assert result["mode"] == "execute"
    # yazma adımında (coder) yazma araçları verilmiş olmalı
    coder_calls = [c for c in calls if c["agent_id"] == "coder"]
    assert coder_calls and "write_file" in coder_calls[0]["tools"]


def test_failed_verification_triggers_limited_retries(monkeypatch, tmp_path):
    _tmp_tasks(monkeypatch, tmp_path)
    monkeypatch.setattr(ai_agent, "chat", _fake_chat_factory([]))

    seq = iter([
        {"ran": True, "exit_code": 1, "passed": False, "stdout_tail": "", "stderr_tail": "boom"},
        {"ran": True, "exit_code": 1, "passed": False, "stdout_tail": "", "stderr_tail": "boom2"},
        {"ran": True, "exit_code": 0, "passed": True, "stdout_tail": "ok", "stderr_tail": ""},
    ])
    monkeypatch.setattr(cm.CodingTaskManager, "run_verification",
                        lambda self, command, timeout=240: next(seq))

    mgr = cm.CodingTaskManager()
    result = asyncio.run(mgr.run("login hatası var, düzelt", mode="execute", confirm=True,
                                 verify_command="pytest -q", max_retries=2,
                                 via_main_manager=False))
    assert result["status"] == "tamamlandi"
    assert result["report"]["6_test_sonuclari"]["dogrulama"]["passed"] is True
    task = cm.get_task(result["task_id"])
    assert task["retries"] == 2


def test_agent_crash_is_recorded_not_lost(monkeypatch, tmp_path):
    _tmp_tasks(monkeypatch, tmp_path)
    monkeypatch.setattr(ai_agent, "chat",
                        _fake_chat_factory([], fail_roles={"bug-fixer"}))
    mgr = cm.CodingTaskManager()
    result = asyncio.run(mgr.run("login hatası var, düzelt", mode="plan",
                                 via_main_manager=False))
    task = cm.get_task(result["task_id"])
    assert any("bug-fixer" in m["recipient"] and not m["success"] for m in task["messages"])
    assert result["report"]["8_basarisiz_islemler"]


def test_parallel_analysis_runs_concurrently(monkeypatch, tmp_path):
    _tmp_tasks(monkeypatch, tmp_path)
    events = []

    async def fake_chat(message, conversation_id=None, history=None, agent_id=None,
                        tools_override=None, system_prefix=None):
        start = time.time()
        await asyncio.sleep(0.06)
        events.append((agent_id, start, time.time()))
        return {"success": True, "response": "ok", "tools_used": []}

    monkeypatch.setattr(ai_agent, "chat", fake_chat)
    mgr = cm.CodingTaskManager()
    asyncio.run(mgr.run("login hatası var, düzelt", mode="plan",
                        via_main_manager=False, parallel_analysis=True))

    # BUGFIX ilk iki adım (debugger, code-analyst) paralel çalışmalı -> zaman aralıkları örtüşür
    first_two = [e for e in events if e[0] in ("debugger", "code-analyst")]
    assert len(first_two) == 2
    (_, s1, e1), (_, s2, e2) = first_two
    overlap = max(s1, s2) < min(e1, e2)
    assert overlap, f"Analiz adımları paralel çalışmadı: {first_two}"


# ---------------------------------------------------------------- HTTP

def _client(monkeypatch, tmp_path):
    _tmp_tasks(monkeypatch, tmp_path)
    monkeypatch.setattr(ai_agent, "chat", _fake_chat_factory([]))
    app = FastAPI()
    app.include_router(cr.router)
    return TestClient(app)


def test_http_health_and_workflows(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/api/v1/coding/health")
    assert r.status_code == 200
    data = r.json()
    assert data["roles_ready"] is True
    assert not data["missing_roles"]

    r = client.get("/api/v1/coding/workflows")
    assert r.status_code == 200
    assert "bugfix" in r.json()["workflows"]


def test_http_run_and_tasks(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.post("/api/v1/coding/run",
                    json={"message": "login hatası var, düzelt", "mode": "plan"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["task_id"]

    r2 = client.get("/api/v1/coding/tasks")
    assert r2.status_code == 200
    assert r2.json()["total"] >= 1

    r3 = client.get(f"/api/v1/coding/tasks/{body['task_id']}")
    assert r3.status_code == 200
    assert r3.json()["task"]["task_id"] == body["task_id"]

    r4 = client.get("/api/v1/coding/tasks/does-not-exist")
    assert r4.status_code == 404
