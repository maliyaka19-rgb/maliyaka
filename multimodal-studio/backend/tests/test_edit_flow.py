"""Düzenleme akışı: mevcut projeye küçük müdahale (ekle/değiştir) tests."""
import asyncio
import os

import ai_agent


NEW_HTML = (
    "<html><body><h1>Yeni Site — Adana Kebap</h1>"
    "<p>Menü güncellendi.</p></body></html>"
)


def _agent_on(tmp_path):
    """Bare agent; tmp_path altında mevcut 'proje' ile."""
    agent = ai_agent.NexusAIAgent.__new__(ai_agent.NexusAIAgent)
    agent.memory = ai_agent.ConversationMemory(max_history=5)
    agent.llm_config = ai_agent.LLMConfig()
    tools = type("T", (), {})()
    tools.working_dir = str(tmp_path)
    tools.execute = None
    agent.tools = tools
    (tmp_path / "index.html").write_text(
        "<html><body><h1>Eski Site</h1><ul><li>Çorba</li></ul></body></html>",
        encoding="utf-8",
    )
    (tmp_path / "styles.css").write_text("body{color:#000}", encoding="utf-8")
    return agent


def test_edit_request_detected(tmp_path):
    agent = _agent_on(tmp_path)
    assert agent._is_edit_request("menüye adana kebap ekle") is True
    assert agent._is_edit_request("renkleri değiştir") is True
    # taze inşa sinyali (isim + fiil) düzenlemeye maske
    assert agent._is_edit_request("yemek sitesi yap") is False
    # proje yoksa düzenleme sayılmaz
    os.remove(os.path.join(str(tmp_path), "index.html"))
    assert agent._is_edit_request("menüye adana kebap ekle") is False


def test_edit_flow_writes_only_changed_file(tmp_path):
    agent = _agent_on(tmp_path)

    async def fake_oneshot(prompt, max_tokens=None):
        assert "MEVCUT DOSYALAR" in prompt  # eski içerik bağlama girdi mi?
        return "### DOSYA: index.html\n```html\n" + NEW_HTML + "\n```"

    agent._local_oneshot = fake_oneshot
    result = asyncio.run(agent._edit_build_files("menüye adana kebap ekle"))
    assert result and result["mode"] == "edit"
    assert result["files"] == ["index.html"]
    on_disk = open(os.path.join(str(tmp_path), "index.html"), encoding="utf-8").read()
    assert "Adana Kebap" in on_disk
    # değişmeyen dosyaya dokunulmadı
    css = open(os.path.join(str(tmp_path), "styles.css"), encoding="utf-8").read()
    assert css == "body{color:#000}"


def test_edit_failure_keeps_files_intact(tmp_path):
    agent = _agent_on(tmp_path)

    async def bad_oneshot(prompt, max_tokens=None):
        return "Üzgünüm, anlayamadım."

    agent._local_oneshot = bad_oneshot
    result = asyncio.run(agent._smart_build_or_edit("menüye adana kebap ekle"))
    assert result and result["files"] == []
    assert "uygulayamadım" in result["response"] or "Değişikliği" in result["response"]
    on_disk = open(os.path.join(str(tmp_path), "index.html"), encoding="utf-8").read()
    assert "Eski Site" in on_disk  # dosya korunur, taze üretim YOK


def test_smart_build_when_no_edit_keywords(tmp_path):
    agent = _agent_on(tmp_path)

    async def fake_build(msg, draft=""):
        return {"files": ["index.html"], "mode": "build",
                "response": "✅ Proje hazır!", "notes": []}

    # inşa adına benziyor ("proje kur") → edit değil build seçilmeli
    async def fake_oneshot(prompt, max_tokens=None):  # build kanadı bunu çağırır
        return ""

    agent._local_oneshot = fake_oneshot
    agent._template_project = lambda msg: [("index.html", "<html></html>")]
    agent._detect_save_target = lambda msg: (None, False)
    result = asyncio.run(agent._smart_build_or_edit("basit bir proje kur"))
    assert result and result.get("mode") == "build"


def test_edit_rejects_truncated_output(tmp_path):
    agent = _agent_on(tmp_path)

    async def truncated(prompt, max_tokens=None):
        # orijinalin %60'ından KISA html → red
        return "### DOSYA: index.html\n```html\n<htm\n```"

    agent._local_oneshot = truncated
    result = asyncio.run(agent._edit_build_files("başlığı büyüt"))
    assert result is None
    on_disk = open(os.path.join(str(tmp_path), "index.html"), encoding="utf-8").read()
    assert "Eski Site" in on_disk
