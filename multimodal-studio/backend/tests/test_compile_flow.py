"""Derleme / çalıştırma akışı testleri (NEXUS kendi kodunu derler)."""
import asyncio
import os

import ai_agent


def _bare(tmp_path):
    agent = ai_agent.NexusAIAgent.__new__(ai_agent.NexusAIAgent)
    agent.memory = ai_agent.ConversationMemory(max_history=5)
    agent.llm_config = ai_agent.LLMConfig()
    tools = type("T", (), {})()
    tools.working_dir = str(tmp_path)
    tools.execute = None
    agent.tools = tools
    # gerçek disk hedef([
    agent._detect_save_target = lambda msg: (None, False)
    return agent


def _student_project(tmp_path):
    agent = _bare(tmp_path)
    files = ai_agent.NexusAIAgent._template_project("ogrenci girisi uygulama")
    ai_agent.NexusAIAgent._write_files_into(str(tmp_path), files)
    return agent


def test_compile_request_detection():
    f = ai_agent.NexusAIAgent._is_compile_request
    assert f("uygulamayı derle")
    assert f("MASA ÜSTÜNDE KLASÖRÜNDEKİ UYGULAMAYI DERLE VE ÇALIŞTIR")
    assert f("projeyi kontrol et")
    assert f("kendini test et")
    assert not f("menüye pizza ekle")
    assert not f("hava durumu uygulaması yap")


def test_code_project_root(tmp_path):
    assert ai_agent.NexusAIAgent._code_project_root(str(tmp_path)) is None
    (tmp_path / "main.py").write_text("print('x')\n", encoding="utf-8")
    assert ai_agent.NexusAIAgent._code_project_root(
        str(tmp_path)) == str(tmp_path)
    # uygulama kökü asla kabul edilmez
    assert ai_agent.NexusAIAgent._code_project_root(
        str(ai_agent._APP_ROOT)) is None


def test_compile_python_and_self_test(tmp_path):
    agent = _student_project(tmp_path)
    report = agent._compile_project(str(tmp_path))
    assert report["ok"]
    assert any("main.py: derlendi" in c for c in report["checks"])
    assert any("Öz test: CHECK: OK" in c for c in report["checks"])
    assert report["main"] and report["main"].endswith("main.py")


def test_compile_python_bad_syntax(tmp_path):
    (tmp_path / "kirik.py").write_text("def x(:\n", encoding="utf-8")
    agent = _bare(tmp_path)
    report = agent._compile_project(str(tmp_path), run_self_test=False)
    assert not report["ok"]
    assert any("kirik.py" in i for i in report["issues"])


def test_compile_html_and_refs(tmp_path):
    (tmp_path / "index.html").write_text(
        "<!DOCTYPE html><html><body><h1>x</h1>"
        "<script src=\"app.js\"></script></body></html>", encoding="utf-8")
    (tmp_path / "app.js").write_text("const a = { b: 1 };\n", encoding="utf-8")
    agent = _bare(tmp_path)
    report = agent._compile_project(str(tmp_path), run_self_test=False)
    assert report["ok"]
    assert any("iskelet" in c for c in report["checks"])


def test_compile_missing_ref_reported(tmp_path):
    (tmp_path / "index.html").write_text(
        "<!DOCTYPE html><html><body>"
        "<link rel=\"stylesheet\" href=\"yok.css\">"
        "</body></html>", encoding="utf-8")
    agent = _bare(tmp_path)
    report = agent._compile_project(str(tmp_path), run_self_test=False)
    assert not report["ok"]
    assert any("yok.css" in i for i in report["issues"])


def test_smart_heading_compile_flow(tmp_path):
    """'...uygulamayı derle' akışı: kök bulunur, rapor üretilir, dosya değişmez."""
    agent = _student_project(tmp_path)
    before = open(tmp_path / "main.py", encoding="utf-8").read()
    result = asyncio.run(agent._smart_build_or_edit(
        "MASA ÜSTÜNDE PROJE KLASÖRÜNDEKİ UYGULAMAYI DERLE"))
    assert result and result.get("mode") == "compile"
    assert "derleme denetimi" in result["response"].lower()
    assert result["files"] == []          # derleme dosya yazmaz
    after = open(tmp_path / "main.py", encoding="utf-8").read()
    assert after == before


def test_compile_not_triggered_by_edit_request(tmp_path):
    """Düzenleme anahtar kelimesi + derle → düzenleme öncelikli (derlemeye düşmez)."""
    files = ai_agent.NexusAIAgent._template_project("gelişmiş yemek sitesi")
    ai_agent.NexusAIAgent._write_files_into(str(tmp_path), files)
    agent = _bare(tmp_path)
    result = asyncio.run(agent._smart_build_or_edit(
        "sitede pizza ekle ve sonra çalıştır"))
    assert result and result.get("mode") != "compile"
