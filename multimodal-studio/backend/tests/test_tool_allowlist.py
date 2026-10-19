"""
Araç allow-list ZORLAMASI (derinlemesine savunma) testleri.

Amaç: ajanın araç izni yalnızca "reklam" düzeyinde kalmasın; executor
gerçekten izin verilmeyen aracı ÇALIŞTIRMASIN. `ai_agent._allowed_tool_names`
ile `tool_executor.execute(allowed=...)` birbiriyle tutarlı olmalı.
"""
import asyncio
import os

from tool_executor import ToolExecutor
from ai_agent import NexusAIAgent


def _executor(tmp_path):
    return ToolExecutor(working_dir=str(tmp_path))


def test_executor_denies_tool_not_in_allowlist(tmp_path):
    ex = _executor(tmp_path)
    res = asyncio.run(ex.execute("write_file",
                                 {"path": "pwned.txt", "content": "x"},
                                 allowed={"read_file", "list_files"}))
    assert res["success"] is False
    assert res.get("denied") is True
    assert not (tmp_path / "pwned.txt").exists(), "İzinsiz araç dosya oluşturmamalı"


def test_executor_allows_tool_in_allowlist(tmp_path):
    ex = _executor(tmp_path)
    res = asyncio.run(ex.execute("write_file",
                                 {"path": "ok.txt", "content": "merhaba"},
                                 allowed={"write_file"}))
    assert res["success"] is True
    assert (tmp_path / "ok.txt").read_text(encoding="utf-8") == "merhaba"


def test_executor_none_means_unrestricted(tmp_path):
    ex = _executor(tmp_path)
    res = asyncio.run(ex.execute("write_file",
                                 {"path": "free.txt", "content": "y"},
                                 allowed=None))
    assert res["success"] is True
    assert (tmp_path / "free.txt").exists()


def test_allowed_tool_names_matches_payload_semantics():
    obj = NexusAIAgent.__new__(NexusAIAgent)  # __init__ (brain/model) atlanır

    # Kısıt yok -> tüm araçlar (yazma dahil)
    obj._active_tools = None
    names = obj._allowed_tool_names()
    assert "write_file" in names and "read_file" in names

    # Salt-okuma allow-list -> yazma araçları YOK
    obj._active_tools = ["read_file", "list_files"]
    names = obj._allowed_tool_names()
    assert "read_file" in names
    assert "write_file" not in names and "edit_file" not in names

    # Boş liste -> hiç araç yok (fail-closed)
    obj._active_tools = []
    assert obj._allowed_tool_names() == set()


def test_readonly_override_blocks_write_end_to_end(tmp_path):
    """ai_agent'ın hesapladığı izin kümesi executor'ı gerçekten bloklar."""
    obj = NexusAIAgent.__new__(NexusAIAgent)
    obj._active_tools = ["read_file", "list_files", "search_files"]
    allowed = obj._allowed_tool_names()

    ex = _executor(tmp_path)
    denied = asyncio.run(ex.execute("write_file", {"path": "x.txt", "content": "z"},
                                    allowed=allowed))
    assert denied.get("denied") is True
    assert not (tmp_path / "x.txt").exists()
