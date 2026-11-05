"""Kendini düzeltme / öz denetim testleri.

NEXUS CORE'un kod yazma kalitesini yükselten üç mekanizmayı sınar:
  1) Deterministik hızlı düzen (renk değişimi, menüye ürün ekleme)
  2) _self_review öz denetimi (referans/iskelet/Python sözdizimi)
  3) Düzenleme akışında LLM'e gitmeden tek geçişte çözüm
"""
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
    return agent


def _project(tmp_path):
    (tmp_path / "index.html").write_text(
        "<!DOCTYPE html><html><head>"
        "<link rel=\"stylesheet\" href=\"styles.css\">"
        "</head><body><h1>Merhaba</h1>"
        "<script src=\"script.js\"></script></body></html>",
        encoding="utf-8",
    )
    (tmp_path / "styles.css").write_text(
        ":root{--brand:#e2542f;--brand-2:#f7a12c}", encoding="utf-8",
    )
    (tmp_path / "script.js").write_text(
        "const MENU = [\n"
        "  { id:1, ad:\"Corba\", kategori:\"Icecek\", fiyat:35, emoji:\"🍲\" },\n"
        "];\n",
        encoding="utf-8",
    )


def test_menu_add_deterministic(tmp_path):
    _project(tmp_path)
    agent = _bare(tmp_path)
    res = agent._deterministic_edits("sitede ADANA KEBAP ekle", str(tmp_path))
    assert res is not None
    files, notes = res
    names = [f for f, _ in files]
    assert "script.js" in names and "styles.css" not in names
    js = dict(files)["script.js"]
    assert 'ad:"Adana Kebap"' in js
    assert "{ id:2" in js              # mevcut id'lerin devamı
    assert "const MENU" in js          # dizi korunur, sıfırdan kurulmaz
    assert any("Adana Kebap" in n for n in notes)


def test_menu_add_skips_stopwords(tmp_path):
    _project(tmp_path)
    agent = _bare(tmp_path)
    res = agent._deterministic_edits(
        "MASA ÜSTÜNDE SITEYE PIZZA EKLE", str(tmp_path))
    assert res is not None
    js = dict(res[0])["script.js"]
    # "MASA ÜSTÜNDE" ürün adına sızmasın
    assert "Masa" not in js.split('ad:"')[1].split('"')[0]


def test_color_change_deterministic(tmp_path):
    _project(tmp_path)
    agent = _bare(tmp_path)
    res = agent._deterministic_edits("renkleri yeşil yap", str(tmp_path))
    assert res is not None
    css = dict(res[0])["styles.css"]
    assert "--brand:#2e7d32" in css
    assert "--brand-2" in css          # diğer değişkenlere dokunulmaz


def test_both_changes_one_pass(tmp_path):
    _project(tmp_path)
    agent = _bare(tmp_path)
    res = agent._deterministic_edits(
        "ADANA KEBAP ekle ve renkleri yeşil olsun", str(tmp_path))
    assert res is not None
    assert {"script.js", "styles.css"} <= {f for f, _ in res[0]}


def test_no_match_returns_none(tmp_path):
    _project(tmp_path)
    agent = _bare(tmp_path)
    assert agent._deterministic_edits("başlığı büyüt", str(tmp_path)) is None


def test_self_review_clean(tmp_path):
    _project(tmp_path)
    ok, issues = ai_agent.NexusAIAgent._self_review(str(tmp_path))
    assert ok and issues == []


def test_self_review_catches_missing_ref(tmp_path):
    _project(tmp_path)
    (tmp_path / "index.html").write_text(
        '<html><body><script src="yok.js"></script></body></html>',
        encoding="utf-8")
    ok, issues = ai_agent.NexusAIAgent._self_review(str(tmp_path))
    assert not ok and any("yok.js" in i for i in issues)


def test_self_review_catches_bad_python(tmp_path):
    (tmp_path / "main.py").write_text("def kirik(:\n  pass\n", encoding="utf-8")
    ok, issues = ai_agent.NexusAIAgent._self_review(str(tmp_path))
    assert not ok and any("main.py" in i for i in issues)


def test_llm_retry_self_correction(tmp_path, monkeypatch):
    """1. LLM denemesi çöp dönerse NEXUS biçim örnekli 2. deneme yapar."""
    _project(tmp_path)
    agent = _bare(tmp_path)
    # deterministik yolu kapalı tut: yalnız LLM akışını sına
    monkeypatch.setattr(
        agent, "_deterministic_edits", lambda m, r: None)
    cagri = {"n": 0}

    async def fake_oneshot(prompt, max_tokens=None):
        cagri["n"] += 1
        if cagri["n"] == 1:
            return "Şu değişiklikleri yaptım: başlık güncellendi."  # çöp
        return ("### DOSYA: index.html\n```html\n"
                "<!DOCTYPE html><html><body><h1>Merhaba</h1>"
                "<script src=\"script.js\"></script></body></html>\n```\n")

    monkeypatch.setattr(agent, "_local_oneshot", fake_oneshot)
    result = asyncio.run(agent._smart_build_or_edit("başlığı büyüt"))
    assert result and result.get("mode") == "edit"
    assert cagri["n"] == 2  # 1. deneme + düzelttirici 2. deneme
    assert any("ikinci deneme" in n for n in result["notes"])
    disk = open(tmp_path / "index.html", encoding="utf-8").read()
    assert "Merhaba" in disk


def test_edit_flow_deterministic_end_to_end(tmp_path):
    """LLM'e gitmeden düzenleme: tek geçiş, dosyalar diskte güncel."""
    _project(tmp_path)
    agent = _bare(tmp_path)
    result = asyncio.run(agent._smart_build_or_edit(
        "sitede adana kebap ekle ve renkleri yesil olsun"))
    assert result and result.get("mode") == "edit-deterministic"
    assert set(result["files"]) == {"script.js", "styles.css"}
    disk_js = open(tmp_path / "script.js", encoding="utf-8").read()
    disk_css = open(tmp_path / "styles.css", encoding="utf-8").read()
    assert 'ad:"Adana Kebap"' in disk_js
    assert "--brand:#2e7d32" in disk_css
    assert "temiz ✓" in result["response"]  # öz denetim raporu yanıtta
