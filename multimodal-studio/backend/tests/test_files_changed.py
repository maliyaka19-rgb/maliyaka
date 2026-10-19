"""
Değişen dosya raporu: "0 dosya değişti" yalanı artık imkânsız.

Sözleşme:
  * `ai_agent.chat` yalnızca BAŞARILI write_file/edit_file sonuçlarındaki `path`i döner.
  * `_run_step` bunu `TaskMessage.changes`e taşır.
  * `run()` tüm adımlardan (retry dahil) birleştirir; rapor `4_degistirilen_dosyalar`
    gerçek listeyi verir.
"""
import asyncio
import json

import pytest

import ai_agent
import coding_manager as cm


def _chat(files_by_agent, counters=None):
    """agent_id -> değiştirilecek dosyalar (liste veya çağrıya göre liste listesi)."""
    async def fake_chat(message, conversation_id=None, history=None, agent_id=None,
                        tools_override=None, system_prefix=None):
        value = files_by_agent.get(agent_id) or []
        if counters is not None and isinstance(value, list) and value and isinstance(value[0], list):
            idx = counters.get(agent_id, 0)
            counters[agent_id] = idx + 1
            files = value[min(idx, len(value) - 1)]
        else:
            files = value
        return {
            "success": True,
            "response": f"[{agent_id}] tamam",
            "conversation_id": conversation_id or "c",
            "tools_used": ["write_file"] if files else [],
            "files_changed": list(files),
            "thinking_steps": [],
        }
    return fake_chat


@pytest.fixture
def tmp_files(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "TASKS_FILE", str(tmp_path / "coding_tasks.json"))
    return tmp_path


def test_report_lists_files_actually_changed(tmp_files, monkeypatch):
    monkeypatch.setattr(ai_agent, "chat", _chat({
        "coder": ["calc.py"],
        "test-engineer": ["test_calc_sub.py"],
    }))

    res = asyncio.run(cm.CodingTaskManager().run(
        "calc.py dosyasina sub fonksiyonu ekle", mode="execute", confirm=True,
        via_main_manager=False,
    ))

    assert res["report"]["4_degistirilen_dosyalar"] == ["calc.py", "test_calc_sub.py"]
    saved = json.loads((tmp_files / "coding_tasks.json").read_text(encoding="utf-8"))
    assert saved[-1]["files_changed"] == ["calc.py", "test_calc_sub.py"]
    assert saved[-1]["messages"][2]["changes"] == ["calc.py"]


def test_no_changes_reports_empty(tmp_files, monkeypatch):
    monkeypatch.setattr(ai_agent, "chat", _chat({}))

    res = asyncio.run(cm.CodingTaskManager().run(
        "selam", mode="plan", via_main_manager=False,
    ))

    assert res["report"]["4_degistirilen_dosyalar"] == []


def test_retry_added_files_are_merged(tmp_files, monkeypatch):
    counters = {}
    monkeypatch.setattr(ai_agent, "chat", _chat({
        "coder": [["a.py"]],
        "test-engineer": [["t1.py"], ["t2.py"]],
    }, counters))

    seq = [
        {"command": "pytest", "ran": True, "passed": False, "exit_code": 1,
         "stdout_tail": "", "stderr_tail": "boom"},
        {"command": "pytest", "ran": True, "passed": True, "exit_code": 0,
         "stdout_tail": "ok", "stderr_tail": ""},
    ]
    monkeypatch.setattr(cm.CodingTaskManager, "run_verification", lambda self, cmd, timeout=240: seq.pop(0))

    res = asyncio.run(cm.CodingTaskManager().run(
        "sub ekle", mode="execute", confirm=True, via_main_manager=False,
        verify_command="pytest", max_retries=1,
    ))

    assert res["status"] == "tamamlandi"
    assert res["report"]["4_degistirilen_dosyalar"] == ["a.py", "t1.py", "t2.py"]

def test_write_step_without_changes_is_flagged(tmp_files, monkeypatch):
    """Canlı E2E'de görüldü: 'coder' başarılı ama 0 dosya. Sessizce yutulmamalı."""
    monkeypatch.setattr(ai_agent, "chat", _chat({}))

    res = asyncio.run(cm.CodingTaskManager().run(
        "sub ekle", mode="execute", confirm=True, via_main_manager=False,
    ))

    risks = res["report"]["9_kalan_riskler"]
    assert any("kanıtsız yazma" in r for r in risks), risks
    assert any(r.startswith("'coder'") for r in risks), risks


def test_plan_mode_does_not_flag_readonly_steps(tmp_files, monkeypatch):
    monkeypatch.setattr(ai_agent, "chat", _chat({}))

    res = asyncio.run(cm.CodingTaskManager().run("selam", mode="plan", via_main_manager=False))

    for risk in res["report"]["9_kalan_riskler"]:
        assert "kanıtsız yazma" not in risk


def test_final_answer_uses_evidence_when_llm_text_missing(tmp_files, monkeypatch):
    """Canlı E2E'de görüldü: doğrulama geçti ama 429 yüzünden 'yanıt üretemiyorum'."""
    fail_text = ("Üzgünüm, şu anda tam yanıt üretemiyorum. "
                 "LLM API'sine erişimde sorun yaşıyorum.")

    async def fake_chat(message, conversation_id=None, history=None, agent_id=None,
                        tools_override=None, system_prefix=None):
        files = ["calc.py"] if agent_id == "coder" else []
        return {
            "success": True,
            "response": fail_text,
            "conversation_id": conversation_id or "c",
            "tools_used": ["write_file"] if files else [],
            "files_changed": files,
            "thinking_steps": [],
        }

    monkeypatch.setattr(ai_agent, "chat", fake_chat)
    monkeypatch.setattr(
        cm.CodingTaskManager, "run_verification",
        lambda self, cmd, timeout=240: {
            "command": cmd, "ran": True, "passed": True, "exit_code": 0,
            "stdout_tail": "2 passed", "stderr_tail": "",
        },
    )

    res = asyncio.run(cm.CodingTaskManager().run(
        "sub ekle", mode="execute", confirm=True, via_main_manager=False,
        verify_command="python -m pytest -q",
    ))

    assert res["status"] == "tamamlandi"
    assert "kanıtlı" in res["final_answer"]
    assert "exit=0" in res["final_answer"]
    assert "calc.py" in res["final_answer"]
    assert res["final_answer_note"]
    assert "üretemiyorum" not in res["final_answer"]
