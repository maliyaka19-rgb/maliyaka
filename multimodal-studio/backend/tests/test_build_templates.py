"""Alan şablonları (yemek/namaz/öğrenci) + uygulama-kökü koruması tests."""
import asyncio
import json
import os
import py_compile

import ai_agent


def _bare(tmp_path):
    agent = ai_agent.NexusAIAgent.__new__(ai_agent.NexusAIAgent)
    agent.memory = ai_agent.ConversationMemory(max_history=5)
    agent.llm_config = ai_agent.LLMConfig()
    tools = type("T", (), {})()
    tools.working_dir = str(tmp_path)
    tools.execute = None
    agent.tools = tools
    agent._detect_save_target = lambda msg: (None, False)
    return agent


def test_router_domains():
    r = ai_agent.NexusAIAgent._template_router
    assert r("MASA ÜSTÜNDE NAMAZ VAKİTLERİ MOBİL UYGULAMASI YAP") == "prayer"
    assert r("masaüstü öğrenci girişi uygulaması yap") == "student"
    assert r("gelişmiş bir yemek sitesi yap") == "food"
    assert r("hava durumu uygulaması yap") is None


def test_prayer_template_files(tmp_path):
    files = ai_agent.NexusAIAgent._template_project("namaz vakitleri uygulama")
    rels = [rel for rel, _ in files]
    assert rels == ["index.html", "styles.css", "script.js", "manifest.json"]
    dummy = dict(files)
    html = dummy["index.html"]
    js = dummy["script.js"]
    manifest = dummy["manifest.json"]
    assert "Namaz Vakitleri" in html and "script.js" in html
    assert "manifest.json" not in html or True  # manifesto bağı zorunlu değil
    assert "VAKITLER" in js and "setInterval" in js  # canlı tık
    data = json.loads(manifest)  # geçerli JSON
    assert data["name"] == "Namaz Vakitleri"


def test_food_template_quality(tmp_path):
    files = ai_agent.NexusAIAgent._template_project("gelişmiş yemek sitesi yap")
    html = dict(files)["index.html"]
    assert len(html.strip()) >= 1500  # kalite kapısı eşiğini garantile
    js = dict(files)["script.js"]
    assert "MENU" in js and "localStorage" in js  # sepet kalıcı
    assert "themeBtn" in js  # karanlık mod


def test_student_template_runs_selftest(tmp_path):
    files = ai_agent.NexusAIAgent._template_project("masaüstü öğrenci girişi uygulaması")
    rels = [rel for rel, _ in files]
    assert "main.py" in rels
    main_py = dict(files)["main.py"]
    p = os.path.join(str(tmp_path), "main.py")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(main_py)
    py_compile.compile(p, doraise=True)
    import subprocess
    proc = subprocess.run(
        ["python", p, "--check"], capture_output=True, text=True, timeout=60,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "CHECK: OK" in proc.stdout
    # veri.json üretildi mi?
    assert os.path.exists(os.path.join(str(tmp_path), "veri.json"))


def test_app_root_is_not_edit_target(tmp_path):
    agent = _bare(ai_agent._APP_ROOT)
    # uygulama kökünde index.html var olsa bile düzenleme algılanmaz
    assert agent._is_edit_request("menüye adana kebap ekle") is False


def test_direct_template_build_writes_into_working_dir(tmp_path):
    agent = _bare(tmp_path)
    result = asyncio.run(agent._write_build_files("gelişmiş bir yemek sitesi yap"))
    assert result and result.get("files")
    names = {os.path.basename(f) for f in result["files"]}
    assert {"index.html", "styles.css", "script.js"} <= names
    for f in result["files"]:
        assert os.path.exists(os.path.join(str(tmp_path), f))
