"""
Görev-yerel çalışma dizini (working_dir) sözleşmesi.

Önceki durum: `/api/v1/coding/run` içindeki `working_dir` YALNIZCA doğrulama
komutunu yönlendiriyordu; araçların dosya yazımları ve komutları süreç genelindeki
proje köküne gidiyordu (güvenlik/ayrışma kusuru).

Yeni sözleşme:
  * `CodingTaskManager.run()` görev boyunca `task_working_dir` contextvar'ını ayarlar.
  * Tüm `ToolExecutor` örnekleri (paylaşılan ajan dahil) bu kökü kullanır.
  * Eşzamanlı görevler birbirini etkilemez; bitince değer geri döner (sızıntı yok).
"""
import asyncio
import os

import pytest

import ai_agent
import coding_manager as cm
from tool_executor import ToolExecutor, task_working_dir


def test_tool_writes_into_task_dir(tmp_path):
    default = tmp_path / "default"
    default.mkdir()
    task = tmp_path / "task"
    task.mkdir()
    ex = ToolExecutor(working_dir=str(default))

    token = task_working_dir.set(str(task))
    try:
        res = asyncio.run(ex.execute("write_file", {"path": "a.txt", "content": "A"}))
    finally:
        task_working_dir.reset(token)

    assert res["success"] is True
    assert (task / "a.txt").read_text(encoding="utf-8") == "A"
    assert not (default / "a.txt").exists(), "görev dizini varken varsayılana yazılmamalı"


def test_default_behaviour_unchanged_without_task_dir(tmp_path):
    default = tmp_path / "default"
    default.mkdir()
    ex = ToolExecutor(working_dir=str(default))

    res = asyncio.run(ex.execute("write_file", {"path": "b.txt", "content": "B"}))

    assert res["success"] is True
    assert (default / "b.txt").read_text(encoding="utf-8") == "B"


def test_task_dir_cannot_escape(tmp_path):
    default = tmp_path / "default"
    default.mkdir()
    task = tmp_path / "task"
    task.mkdir()
    ex = ToolExecutor(working_dir=str(default))

    token = task_working_dir.set(str(task))
    try:
        with pytest.raises(ValueError):
            ex._resolve_path("../evil.txt")
        res = asyncio.run(ex.execute("write_file", {"path": "../evil.txt", "content": "x"}))
    finally:
        task_working_dir.reset(token)

    assert res["success"] is False
    assert not (tmp_path / "evil.txt").exists()


def test_execute_command_runs_in_task_dir(tmp_path):
    default = tmp_path / "default"
    default.mkdir()
    task = tmp_path / "task"
    task.mkdir()
    ex = ToolExecutor(working_dir=str(default))

    token = task_working_dir.set(str(task))
    try:
        res = asyncio.run(ex.execute(
            "execute_command",
            {"command": 'python -c "import os;print(os.getcwd())"'},
        ))
    finally:
        task_working_dir.reset(token)

    assert res["success"] is True, res
    out = (res.get("stdout") or "").strip()
    assert os.path.realpath(out) == os.path.realpath(str(task))


def test_concurrent_tasks_are_isolated(tmp_path):
    ex = ToolExecutor(working_dir=str(tmp_path / "base"))

    async def writer(name, directory):
        token = task_working_dir.set(str(directory))
        try:
            await asyncio.sleep(0)
            return await ex.execute("write_file", {"path": f"{name}.txt", "content": name})
        finally:
            task_working_dir.reset(token)

    async def main():
        return await asyncio.gather(
            writer("a", tmp_path / "a"),
            writer("b", tmp_path / "b"),
        )

    results = asyncio.run(main())

    assert all(r["success"] for r in results)
    assert (tmp_path / "a" / "a.txt").read_text(encoding="utf-8") == "a"
    assert (tmp_path / "b" / "b.txt").read_text(encoding="utf-8") == "b"


def test_manager_sets_task_dir_for_tools_and_resets(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "TASKS_FILE", str(tmp_path / "tasks.json"))
    ws = tmp_path / "ws"
    ws.mkdir()
    seen = {}

    async def fake_chat(message, conversation_id=None, history=None, agent_id=None,
                        tools_override=None, system_prefix=None):
        # Kasıtlı olarak FARKLI varsayılanla yeni bir executor: contextvar kazanmalı.
        ex = ToolExecutor(working_dir=str(tmp_path))
        files = []
        if agent_id == "coder":
            res = await ex.execute("write_file", {"path": "made.py", "content": "x = 1\n"})
            seen["write"] = res
            files = ["made.py"]
        seen["dir"] = task_working_dir.get()
        return {
            "success": True,
            "response": "ok",
            "conversation_id": conversation_id or "c",
            "tools_used": ["write_file"] if files else [],
            "files_changed": files,
            "thinking_steps": [],
        }

    monkeypatch.setattr(ai_agent, "chat", fake_chat)

    res = asyncio.run(cm.CodingTaskManager(working_dir=str(ws)).run(
        "sub ekle", mode="execute", confirm=True, via_main_manager=False,
    ))

    assert seen["write"]["success"] is True
    assert (ws / "made.py").read_text(encoding="utf-8") == "x = 1\n"
    assert not (tmp_path / "made.py").exists(), "varsayılan dizine sızmamalı"
    assert os.path.realpath(seen["dir"]) == os.path.realpath(str(ws))
    assert res["report"]["4_degistirilen_dosyalar"] == ["made.py"]
    assert task_working_dir.get() is None, "görev sonrası context sızmamalı"


def test_manager_rejects_missing_dir(tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(cm.CodingTaskManager(working_dir=str(tmp_path / "yok")).run("selam"))

    assert task_working_dir.get() is None
