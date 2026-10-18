"""Sır temizleme (secret redaction) regresyon testleri.

Kök neden (D-021): `httpx` istemcisi istek URL'lerini INFO seviyesinde loglar.
Telegram Bot API'nin URL biçimi token'ı içerir:

    https://api.telegram.org/bot<ID>:<TOKEN>/getMe

Bu yüzden bot token'ı uygulama loglarına **düz metin** olarak sızıyordu.
`SecretRedactingFilter` bu desenleri log kaydı oluşurken temizler.

Not: Bu dosyadaki token'lar **uydurma**dır (gerçek sır içermez).
"""
import logging

from app import SecretRedactingFilter

FAKE_TELEGRAM_TOKEN = "1234567890:AAFakeFakeFakeFakeFakeFakeFake12345"
FAKE_GROQ_KEY = "gsk_FakeFakeFakeFakeFakeFakeFakeFake1234"


def _filtered(message):
    """Mesajı filtreleyip sonuç metnini döndürür."""
    record = logging.LogRecord(
        name="httpx", level=logging.INFO, pathname=__file__, lineno=1,
        msg=message, args=(), exc_info=None,
    )
    kept = SecretRedactingFilter().filter(record)
    assert kept is True, "filtre kaydı düşürmemeli (yalnızca temizler)"
    return record.getMessage()


def test_telegram_token_in_httpx_url_is_redacted():
    message = (
        "HTTP Request: GET https://api.telegram.org/bot"
        f"{FAKE_TELEGRAM_TOKEN}/getMe \"HTTP/1.1 200 OK\""
    )
    cleaned = _filtered(message)
    assert FAKE_TELEGRAM_TOKEN not in cleaned
    assert "bot[GIZLI]" in cleaned
    # URL'in geri kalanı korunur (log hâlâ işe yarar).
    assert "api.telegram.org" in cleaned
    assert "getMe" in cleaned


def test_groq_key_is_redacted():
    cleaned = _filtered(f"Groq hatası: Authorization Bearer {FAKE_GROQ_KEY} geçersiz")
    assert FAKE_GROQ_KEY not in cleaned
    assert "[GIZLI_ANAHTAR]" in cleaned


def test_openai_style_key_is_redacted():
    fake = "sk-" + "A" * 32
    cleaned = _filtered(f"api key {fake} kullanıldı")
    assert fake not in cleaned
    assert "[GIZLI_ANAHTAR]" in cleaned


def test_normal_message_is_unchanged():
    message = "Ajan başlatıldı ve araçlar bağlandı"
    assert _filtered(message) == message


def test_getMessage_with_args_is_redacted():
    """%s biçimli loglarda da temizlenmeli."""
    record = logging.LogRecord(
        name="httpx", level=logging.INFO, pathname=__file__, lineno=1,
        msg="URL: %s", args=("https://api.telegram.org/bot" + FAKE_TELEGRAM_TOKEN + "/getUpdates",),
        exc_info=None,
    )
    SecretRedactingFilter().filter(record)
    out = record.getMessage()
    assert FAKE_TELEGRAM_TOKEN not in out
    assert "getUpdates" in out


def test_filter_is_attached_to_httpx_logger():
    """Filtre httpx/uvicorn gibi gürültülü logger'lara bağlı olmalı."""
    for name in ("httpx", "httpcore", "uvicorn"):
        filters = logging.getLogger(name).filters
        assert any(isinstance(f, SecretRedactingFilter) for f in filters), name
