"""
Telegram Bot API Routes
=======================
Telegram bot entegrasyonunu yönetmek için HTTP uç noktaları.

``telegram_bot`` modülü yalnızca fonksiyon içlerinde (lazy) içe aktarılır;
böylece bu router import edildiğinde polling başlamaz.

Hiçbir uç nokta ham token'ı döndürmez.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"])


# ---------------------------------------------------------------------------
# Pydantic modelleri
# ---------------------------------------------------------------------------

class ConfigRequest(BaseModel):
    token: Optional[str] = Field(default=None, description="Bot token (yalnızca gönderim)")
    allowed_chat_ids: Optional[List[int]] = None
    enabled: Optional[bool] = None
    default_agent_id: Optional[str] = None


class SendRequest(BaseModel):
    chat_id: int
    text: str


# ---------------------------------------------------------------------------
# Yardımcı
# ---------------------------------------------------------------------------

def _status_payload() -> dict:
    """Ham token içermeyen durum yanıtı oluşturur."""
    import telegram_bot as tb  # lazy import

    cfg = tb.load_config()
    bot = tb.get_bot()
    token_set = bool(cfg.get("token_enc") or cfg.get("token"))
    return {
        "success": True,
        "enabled": bool(cfg.get("enabled")),
        "running": bool(bot.running) if bot is not None else False,
        "token_set": token_set,
        "allowed_chat_ids": list(cfg.get("allowed_chat_ids") or []),
        "default_agent_id": cfg.get("default_agent_id") or "main-manager",
        "bot_username": getattr(bot, "bot_username", None) if bot is not None else None,
    }


# ---------------------------------------------------------------------------
# Uç noktalar
# ---------------------------------------------------------------------------

@router.get("/status")
async def telegram_status() -> dict:
    """Telegram bot entegrasyonunun durumu (token asla döndürülmez)."""
    try:
        return _status_payload()
    except Exception as exc:  # pragma: no cover - savunma amaçlı
        raise HTTPException(status_code=400, detail=f"Durum okunamadı: {exc}")


@router.post("/config")
async def set_telegram_config(req: ConfigRequest) -> dict:
    """Ayarları kaydeder; çalışıyorsa yeniden başlatır."""
    import telegram_bot as tb  # lazy import

    try:
        cfg = tb.load_config()

        if req.token is not None:
            # Önceki token'ı (şifreli/düz) temizle; save_config düz metni şifreler.
            cfg.pop("token_enc", None)
            cfg.pop("token", None)
            stripped = req.token.strip()
            if stripped:
                cfg["token"] = stripped

        if req.allowed_chat_ids is not None:
            cfg["allowed_chat_ids"] = [int(x) for x in req.allowed_chat_ids]

        if req.enabled is not None:
            cfg["enabled"] = bool(req.enabled)

        if req.default_agent_id is not None:
            cfg["default_agent_id"] = req.default_agent_id.strip() or "main-manager"

        saved = tb.save_config(cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Ayar kaydedilemedi: {exc}")

    # Çalışıyorsa durdur ve (etkinse) yeni ayarlarla yeniden başlat.
    bot = tb.get_bot()
    was_running = bool(bot is not None and bot.running)
    if was_running:
        await tb.stop_bot()

    has_token = bool(saved.get("token_enc") or saved.get("token"))
    if saved.get("enabled") and has_token:
        try:
            await tb.start_bot_from_config()
        except Exception:
            # Bot başlatılamasa bile ayarlar kaydedilmiş sayılır.
            pass

    return _status_payload()


@router.post("/start")
async def start_telegram() -> dict:
    """Kayıtlı ayarlardan botu başlatır."""
    import telegram_bot as tb  # lazy import

    cfg = tb.load_config()
    if not (cfg.get("token_enc") or cfg.get("token")):
        raise HTTPException(
            status_code=400,
            detail="Telegram token yapılandırılmamış. Önce /config ile token girin.",
        )
    try:
        await tb.start_bot_from_config()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Bot başlatılamadı: {exc}")
    return _status_payload()


@router.post("/stop")
async def stop_telegram() -> dict:
    """Çalışan botu durdurur."""
    import telegram_bot as tb  # lazy import

    try:
        await tb.stop_bot()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Bot durdurulamadı: {exc}")
    return _status_payload()


@router.post("/send")
async def send_telegram(req: SendRequest) -> dict:
    """Çalışan bot üzerinden mesaj gönderir."""
    import telegram_bot as tb  # lazy import

    bot = tb.get_bot()
    if bot is None or not bot.running:
        return {"success": False, "error": "Bot çalışmıyor."}

    text = (req.text or "").strip()
    if not text:
        return {"success": False, "error": "Gönderilecek metin boş."}

    try:
        await bot.send_message(req.chat_id, text)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True}
