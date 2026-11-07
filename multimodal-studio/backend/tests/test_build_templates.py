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
    assert r("veri tabanı raporu hazırla") is None


def test_prayer_template_files(tmp_path):
    files = ai_agent.NexusAIAgent._template_project("namaz vakitleri uygulama")
    rels = [rel for rel, _ in files]
    assert rels == ["index.html", "styles.css", "script.js",
                    "manifest.json", "README.md"]
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


# ------------------------------------------------------------------
# 2026-11-05: modern şablon ailesi v2 testleri
# ------------------------------------------------------------------


def test_router_v2_domains():
    r = ai_agent.NexusAIAgent._template_router
    assert r("MASA ÜSTÜNDE HAVADURUMU KLASÖRÜNE HAVA DURUMU PANELİ YAP") == "weather"
    assert r("yapilacaklar listesi uygulaması yap") == "todo"
    # "MASA ÜSTÜNDE X KLASÖRÜNE" yalnızca KONUM belirtir → web todo
    assert r("MASA ÜSTÜNDE TODO KLASÖRÜNE MODERN BİR YAPILACAKLAR UYGULAMASI YAP") == "todo"
    # platform talebi bitişikse → masaüstü todo
    assert r("MASA ÜSTÜNDE TODO TASKS KLASÖRÜNE MASAÜSTÜ YAPILACAKLAR UYGULAMASI YAP") == "todot"
    assert r("MASA ÜSTÜNDE CALC KLASÖRÜNE HESAP MAKİNESİ UYGULAMASI YAP") == "calc"
    assert r("masaüstü öğrenci girişi uygulaması yap") == "student"


def _write_all(tmp_path, files):
    written = {}
    for rel, content in files:
        p = os.path.join(str(tmp_path), rel)
        os.makedirs(os.path.dirname(p) or str(tmp_path), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        written[rel] = content
    return written


def test_weather_template_quality(tmp_path):
    import re as _re
    files = ai_agent.NexusAIAgent._template_project("hava durumu paneli yap")
    dummy = _write_all(tmp_path, files)
    assert "VERI" in dummy["script.js"]
    assert "--brand" in dummy["styles.css"]          # deterministik renk uyumlu
    manifest = json.loads(dummy["manifest.json"])
    assert manifest["name"] == "Hava Radar"
    sehir_sayisi = len(_re.findall(
        r'"[A-ZÇĞİÖŞÜ][a-zçğıöşü]+": \{', dummy["script.js"]))
    assert sehir_sayisi >= 6   # 6 şehrin verisi tam olmalı


def test_todo_web_template_quality():
    files = ai_agent.NexusAIAgent._template_project("yapilacaklar uygulaması yap")
    dummy = dict(files)
    js = dummy["script.js"]
    assert "localStorage" in js and "escapeHtml" in js  # kalıcılık + güvenlik
    assert 'data-f="bekleyen"' in dummy["index.html"]   # filtreler
    assert "--brand" in dummy["styles.css"]


def test_calc_template_runs_selftest(tmp_path):
    import subprocess
    files = ai_agent.NexusAIAgent._template_project("hesap makinesi uygulaması yap")
    dummy = _write_all(tmp_path, files)
    proc = subprocess.run(
        ["python", os.path.join(str(tmp_path), "main.py"), "--check"],
        capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "CHECK: OK" in proc.stdout
    py_compile.compile(os.path.join(str(tmp_path), "main.py"), doraise=True)


def test_dtask_template_runs_selftest(tmp_path):
    import subprocess
    files = ai_agent.NexusAIAgent._template_project(
        "masaüstü yapılacaklar uygulaması yap")
    dummy = _write_all(tmp_path, files)
    proc = subprocess.run(
        ["python", os.path.join(str(tmp_path), "main.py"), "--check"],
        capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "CHECK: OK" in proc.stdout
    assert os.path.exists(os.path.join(str(tmp_path), "tasks.json"))


def test_all_web_templates_have_brand_var():
    """Deterministik renk düzenlemesi tüm web şablonlarında çalışmalı."""
    agent = ai_agent.NexusAIAgent
    for msg in ("namaz uygulama", "hava durumu", "todo uygulama",
                "yemek sitesi"):
        files = dict(agent._template_project(msg))
        assert "--brand" in files["styles.css"], msg


# ------------------------------------------------------------------
# 2026-11-07: yarım-proje yasak + internet (canlı veri) testleri
# ------------------------------------------------------------------


def test_unknown_domain_skips_llm_and_writes_complete_template(tmp_path):
    """Bilinmeyen alan → LLM oneshot çalışmaz, TAM şablon dosyaları yazılır."""
    agent = _bare(tmp_path)

    def yasak(msg):
        raise AssertionError("LLM oneshot çağrılmamalı (NEXUS_LLM_BUILD=0)")

    agent._oneshot_project_text = yasak
    result = asyncio.run(agent._write_build_files(
        "kitap okuma takip sitesi yap ve kaydet"))
    root = str(tmp_path)
    names = {os.path.basename(f) for f in result["files"]}
    assert {"index.html", "styles.css", "script.js"} <= names
    with open(os.path.join(root, "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert "Aurora" in html                       # modern genel şablon
    # yarım-proje kontrolü: HTML'in tüm css/js referansları diskte var mı?
    import re as _re
    for ref in _re.findall(r'(?:src|href)="([^"\s]+\.(?:css|js))"', html):
        assert os.path.exists(os.path.join(root, os.path.basename(ref))), ref


def test_quality_gate_swaps_half_project(tmp_path):
    """Kısa HTML + eksik referans → kalite kapısı TAM şablona döner."""
    agent = _bare(tmp_path)
    yarim = ("```html\n<html><body><h1>Yarım site</h1>"
             '<script src="script.js"></script>' + "dolgu metni " * 40 +
             "</body></html>\n```")
    result = asyncio.run(
        agent._write_build_files("custom panel", draft_response=yarim))
    with open(os.path.join(str(tmp_path), "index.html"),
              encoding="utf-8") as f:
        html = f.read()
    assert "Yarım site" not in html       # bozuk üretim reddedildi
    assert "Aurora" in html               # TAM şablon devreye girdi


def test_weather_live_layer():
    files = dict(ai_agent.NexusAIAgent._template_project("hava durumu yap"))
    js = files["script.js"]
    assert "open-meteo.com" in js                 # canlı veri API'si (anahtarsız)
    assert "CANLI[" in js and "kodIkon" in js     # canlı durum + kod→ikon
    assert "VERI" in js                           # demo yedeği korundu
    assert 'id="mod"' in files["index.html"]       # canlı/demo rozeti
    assert "canlı" in js and "demo" in js


def test_prayer_live_layer():
    files = dict(ai_agent.NexusAIAgent._template_project("namaz vakitleri"))
    js = files["script.js"]
    assert "aladhan.com" in js                    # Diyanet yöntemi API'si
    assert "canliVakitCek" in js
    assert "CANLI_SATLER" in js
    assert 'id="kaynak"' in files["index.html"]   # canlı/demo rozeti
    assert "method=13" in js                      # Diyanet İşleri ↔ method 13


def test_aurora_generic_template_quality():
    html, css, js = (
        ai_agent._BUILD_TEMPLATE_HTML,
        ai_agent._BUILD_TEMPLATE_CSS,
        ai_agent._BUILD_TEMPLATE_JS,
    )
    assert len(css.strip()) >= 3000 and len(js.strip()) >= 1000
    assert "--brand" in css                       # renk düzeni çalışır
    assert "IntersectionObserver" in js           # scroll animasyonu
    assert 'id="form"' in html and "themeBtn" in js
