"""
Kök adres (`/`) davranışı.

Amaç: tek servis dağıtımında (yerel/Render) kök adres doğrudan arayüzü açsın;
yalnızca backend çalışan ortamlarda (arayüz kopyalanmayan Docker imajı) eski
JSON bilgisi korunsun. API bilgisi her durumda `/api/info` üzerinden erişilebilir.
"""
from fastapi.testclient import TestClient

import app as app_module


def test_root_redirects_to_ui_when_ui_available():
    client = TestClient(app_module.app, follow_redirects=False)
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/sohbet.html"


def test_root_follows_redirect_to_real_html():
    client = TestClient(app_module.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.url.path == "/sohbet.html"
    assert "<html" in resp.text.lower()


def test_ui_entry_is_served_directly():
    client = TestClient(app_module.app)
    resp = client.get("/sohbet.html")
    assert resp.status_code == 200
    assert "<html" in resp.text.lower()


def test_api_info_is_always_available():
    client = TestClient(app_module.app)
    resp = client.get("/api/info")
    assert resp.status_code == 200
    body = resp.json()
    assert "mesaj" in body
    assert body["endpointler"]["arayuz"] == "/sohbet.html"
    assert body["endpointler"]["belgeler"] == "/docs"


def test_root_falls_back_to_json_when_ui_missing(monkeypatch):
    """Arayüz kopyalanmayan imajlarda (Docker) kök adres JSON döndürmeye devam eder."""
    real_exists = app_module.os.path.exists

    def fake_exists(path):
        if str(path).replace("\\", "/").endswith("sohbet.html"):
            return False
        return real_exists(path)

    monkeypatch.setattr(app_module.os.path, "exists", fake_exists)

    client = TestClient(app_module.app, follow_redirects=False)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "mesaj" in resp.json()
