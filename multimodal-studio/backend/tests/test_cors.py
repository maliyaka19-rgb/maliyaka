"""CORS yapılandırması regresyon testleri.

Kök neden: masaüstü (Electron) uygulaması arayüzü `http://127.0.0.1:8090`
gibi bir yerel adresten servis eder. Bu origin izin listesinde olmadığı için
tarayıcı tüm API çağrılarını CORS ile blokladı ve uygulama "Failed to fetch"
verdi.

Düzeltme: geri döngü (loopback) adresleri porttan bağımsız izinli
(`allow_origin_regex`). Masaüstü uygulaması 8090 doluysa rastgele bir port
seçebildiği için bu gereklidir. Dış origin'ler yine reddedilir.
"""
from fastapi.testclient import TestClient

from app import app


def _preflight(client, origin, path="/api/v1/auth/guest"):
    return client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_desktop_origin_8090_allowed():
    client = TestClient(app)
    r = _preflight(client, "http://127.0.0.1:8090")
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:8090"


def test_random_loopback_port_allowed():
    """Masaüstü uygulaması boş bir port seçebilir; porttan bağımsız izinli olmalı."""
    client = TestClient(app)
    r = _preflight(client, "http://127.0.0.1:8099")
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:8099"


def test_frontend_8080_still_allowed():
    client = TestClient(app)
    r = _preflight(client, "http://localhost:8080")
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:8080"


def test_external_origin_rejected():
    """Güvenlik: dış origin'ler izin verilmemeli."""
    client = TestClient(app)
    r = _preflight(client, "http://evil.example.com")
    assert r.headers.get("access-control-allow-origin") is None


def test_loopback_regex_does_not_match_lookalike():
    """`127.0.0.1.evil.com` geri döngü sayılmamalı (regex tam eşleşme)."""
    client = TestClient(app)
    r = _preflight(client, "http://127.0.0.1.evil.com")
    assert r.headers.get("access-control-allow-origin") is None
