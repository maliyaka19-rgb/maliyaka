"""
Öğrenme döngüsü: görev sonunda OTOMATİK, denetimli içgörü üretimi.

Doğrulanan sözleşme:
  * Görev bitince içgörü üretimi kendiliğinden çalışır (`run` sonucunda `insights`).
  * LLM kullanılmaz; sonuç deterministik ve `applied=False`.
  * Öğrenme katmanı hata verirse GÖREV DÜŞMEZ.
  * `NEXUS_AUTO_INSIGHTS=0` ile kapatılabilir (testlerde varsayılan kapalı).
"""
import asyncio
import json

import pytest

import ai_agent
import coding_insights as cins
import coding_manager as cm


def _task(task_id="t1", status="tamamlandi", verification=None):
    return {
        "task_id": task_id,
        "request": "ornek gorev",
        "task_type": "general",
        "mode": "plan",
        "status": status,
        "verification": verification,
        "files_changed": [],
        "tools_used": [],
        "retries": 0,
        "remaining_issues": [],
        "roles": [],
    }


@pytest.fixture
def files(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "TASKS_FILE", str(tmp_path / "coding_tasks.json"))
    monkeypatch.setattr(cins, "INSIGHTS_FILE", str(tmp_path / "coding_insights.json"))
    monkeypatch.setenv("NEXUS_AUTO_INSIGHTS", "1")
    return tmp_path


def test_disabled_by_default_in_tests():
    assert cm.CodingTaskManager._auto_insights_enabled() is False

    res = cm.CodingTaskManager._refresh_insights()

    assert res["ok"] is True
    assert "skipped" in res
    assert res["applied"] is False


def test_enabled_generates_deterministic_insights(files):
    (files / "coding_tasks.json").write_text(json.dumps([_task()]), encoding="utf-8")
    assert cm.CodingTaskManager._auto_insights_enabled() is True

    res = cm.CodingTaskManager._refresh_insights()

    assert res["ok"] is True, res
    assert res["applied"] is False, "denetimli: otomatik uygulama YOK"
    assert res["created"] >= 1
    assert res["tasks_analyzed"] == 1

    saved = json.loads((files / "coding_insights.json").read_text(encoding="utf-8"))
    kinds = {i["kind"] for i in saved}
    assert "kanitsiz_tamamlama" in kinds
    assert all(i["status"] == cins.STATUS_PROPOSAL for i in saved)
    assert all(i["applied"] is False for i in saved)


def test_insight_failure_never_breaks_task(files, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("analiz patladi")

    monkeypatch.setattr(cins, "generate_insights", boom)

    res = cm.CodingTaskManager._refresh_insights()

    assert res["ok"] is False
    assert res["error"] == "RuntimeError"
    assert res["applied"] is False


def test_run_returns_insights_automatically(files, monkeypatch):
    async def fake_chat(message, conversation_id=None, history=None, agent_id=None,
                        tools_override=None, system_prefix=None):
        return {
            "success": True,
            "response": f"[{agent_id}] tamam",
            "conversation_id": conversation_id or "c",
            "tools_used": [],
            "thinking_steps": [],
        }

    monkeypatch.setattr(ai_agent, "chat", fake_chat)

    manager = cm.CodingTaskManager()
    result = asyncio.run(manager.run("selam", mode="plan", via_main_manager=False))

    assert result["status"] == "tamamlandi"
    assert result["insights"]["ok"] is True
    assert result["insights"]["applied"] is False
    assert result["insights"]["tasks_analyzed"] >= 1
    assert (files / "coding_insights.json").exists(), "içgörü dosyası yazılmalı"
