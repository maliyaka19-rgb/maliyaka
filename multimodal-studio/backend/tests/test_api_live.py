"""Canlı API entegrasyon testleri (T-008).

Varsayılan olarak ÇALIŞMAZ (marker: live) — pytest.ini `-m "not live"` ile hariç tutulur.
Bir backend sunucusu gerektirir: http://localhost:8000

Çalıştırma:
    pytest tests/test_api_live.py -m live

Kimlik bilgisi GÜVENLİK gereği koda gömülmez; ortam değişkeninden okunur:
    set NEXUS_TEST_EMAIL=...
    set NEXUS_TEST_PASSWORD=...
Kimlik yoksa auth gerektiren testler atlanır (skip).
"""
import os
import pytest
import httpx

pytestmark = pytest.mark.live

BASE = os.getenv("NEXUS_API_BASE", "http://localhost:8000")
EMAIL = os.getenv("NEXUS_TEST_EMAIL")
PASSWORD = os.getenv("NEXUS_TEST_PASSWORD")


def _server_up() -> bool:
    try:
        return httpx.get(f"{BASE}/health", timeout=3).status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def client():
    if not _server_up():
        pytest.skip("Backend çalışmıyor — canlı testler atlandı")
    with httpx.Client(base_url=BASE, timeout=180) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    if not (EMAIL and PASSWORD):
        pytest.skip("NEXUS_TEST_EMAIL/PASSWORD tanımlı değil — auth testleri atlandı")
    r = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code != 200:
        pytest.skip(f"Login başarısız ({r.status_code})")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.parametrize("path", [
    "/", "/health",
    "/api/v1/models/catalog", "/api/v1/models/providers", "/api/v1/models/active",
    "/api/v1/agents", "/api/v1/agents/tools/available",
    "/api/v1/ai/info", "/api/v1/ai/conversations", "/api/v1/ai/learning/stats",
    "/api/v1/agent/tools", "/api/v1/agent/sessions", "/api/v1/agent/memory/stats",
    "/api/v1/brain/stats", "/api/v1/brain/skills", "/api/v1/brain/lessons",
    "/api/v1/brain/experiences", "/api/v1/brain/reflections",
    "/api/v1/fs/drives", "/api/v1/fs/home", "/api/v1/fs/current-project",
    "/api/v1/project/stats", "/api/v1/project/tree",
    "/api/v1/learning/report", "/api/v1/learning/summary",
])
def test_get_endpoints_200(client, path):
    r = client.get(path)
    assert r.status_code == 200, f"{path} -> {r.status_code}"


def test_agent_status_regression(client):
    """Regresyon: boş durumda 500 vermemeli (eski hata: eksik şema)."""
    r = client.get("/api/v1/agent/status")
    assert r.status_code == 200, f"agent/status -> {r.status_code}: {r.text[:200]}"
    body = r.json()
    for field in ("session_id", "state", "current_step", "total_steps", "memory_counts"):
        assert field in body, f"eksik alan: {field}"


def test_auth_me(client, auth_headers):
    r = client.get("/api/v1/auth/me", headers=auth_headers)
    assert r.status_code == 200


def test_chat_returns_response(client, auth_headers):
    r = client.post("/api/v1/ai/chat", json={"message": "Tek kelimeyle merhaba de."}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True
    assert body.get("response")


def test_image_proxy_rejects_foreign_url(client):
    """Güvenlik: pollinations.ai dışı URL reddedilmeli (400)."""
    r = client.get("/api/v1/image/proxy", params={"url": "https://evil.example.com/x.jpg"})
    assert r.status_code == 400
