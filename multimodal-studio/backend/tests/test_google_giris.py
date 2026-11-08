"""Google (Gmail) giriş API'si — güvenlik/durum testleri."""
import asyncio

import auth_routes as ar


def test_config_kapali_ken_istemci_gizli(monkeypatch):
    monkeypatch.setattr(ar, "GOOGLE_CLIENT_ID", "")
    cfg = asyncio.run(ar.google_oauth_config())
    assert cfg == {"enabled": False, "client_id": ""}


def test_config_acik_ken_client_id_doner(monkeypatch):
    monkeypatch.setattr(ar, "GOOGLE_CLIENT_ID", "test-gid-1")
    cfg = asyncio.run(ar.google_oauth_config())
    assert cfg["enabled"] is True
    assert cfg["client_id"] == "test-gid-1"


def test_yapilandirilmamis_google_url_sahte_kullanici_uretirmez(monkeypatch):
    """GÜVENLİK: eski mock akışı parolasız gerçek oturum veriyordu — yasak."""
    monkeypatch.setattr(ar, "GOOGLE_CLIENT_ID", "")
    cevap = asyncio.run(ar.google_oauth_url(None))
    assert cevap["enabled"] is False
    assert cevap["url"] is None
    assert "mock" not in cevap


def test_yapilandirilmamis_apple_url_sahte_kullanici_uretirmez(monkeypatch):
    monkeypatch.setattr(ar, "APPLE_CLIENT_ID", "")
    cevap = asyncio.run(ar.apple_oauth_url(None))
    assert cevap["enabled"] is False
    assert cevap["url"] is None


def test_yapilandirilmis_google_url_uretilir(monkeypatch):
    monkeypatch.setattr(ar, "GOOGLE_CLIENT_ID", "test-gid-1")
    cevap = asyncio.run(ar.google_oauth_url(None))
    assert "accounts.google.com" in cevap["url"]
    assert "client_id=test-gid-1" in cevap["url"]
    assert cevap.get("state")
