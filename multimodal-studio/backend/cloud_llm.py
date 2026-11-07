"""BYOK bulut LLM istemcisi — HER KULLANICI KENDİ ANAHTARINI KULLANIR.

Güvenlik kuralı: Anahtar sunucuda SAKLANMAZ. Kullanıcının tarayıcısında
(localStorage) tutulur ve her sohbet isteğinde özel bir başlıklara gönderilir:

    X-Nexus-Llm-Key   : API anahtarı (sohbetler için)
    X-Nexus-Llm-Model : (isteğe bağlı) model kimliği, örn. z-ai/glm-4.5-air:free
    X-Nexus-Llm-Base  : (isteğe bağlı) OpenAI-uyumlu temel adres
                          (varsayılan: OpenRouter; Z.ai için
                           https://api.z.ai/api/paas/v4 girilebilir)

Anahtar yalnız İSTEĞİ gönderen kullanıcının çağrısı için kullanılır:
başka hiçbir kullanıcı/sistem o anahtarı göremez veya kullanamaz, sunucu
diske yazmaz, loglamaz.

OpenAI-uyumlu uç noktalarla çalışır (OpenRouter, Z.ai vb.) ve local_llm.chat
ile AYNI sözleşmeyi döndürür: {"success": bool, "data": {...}, ...}
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nexus-agent-v6")

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
# GLM-5.3-Flash: OpenRouter'da ücretsiz katman yok; ama kendi anahtarınla
# yeterince cüzi fiyat (1M girdi ≈ $0.15). Ayrıca Z.ai anahtarları için
# temel adres https://api.z.ai/api/paas/v4 girilebilir.
DEFAULT_MODEL = "z-ai/glm-5.3-flash"


def cloud_timeout() -> float:
    try:
        return max(30.0, float(os.getenv("NEXUS_CLOUD_LLM_TIMEOUT", "180")))
    except ValueError:
        return 180.0


def mask(key: str) -> str:
    """Anahtarı log/yanıt gösterimine uygun gizler."""
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) <= 10:
        return k[:3] + "***"
    return k[:6] + "***" + k[-4:]


def normalized(base_url: Optional[str]) -> Optional[str]:
    """Temel adres doğrulaması: yalnız https veya localhost/http güvenli."""
    b = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not b.startswith(("http://", "https://")):
        return None
    if b.startswith("http://") and not (
            "127.0.0.1" in b or "localhost" in b):
        return None
    return b


async def chat(
    messages: List[Dict[str, Any]],
    key: str,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    timeout: Optional[float] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: str = "auto",
    transport: Any = None,
) -> Dict[str, Any]:
    """OpenAI-uyumlu bulut /chat/completions çağrısı (BYOK).

    ``local_llm.chat`` ile aynı kelime sözleşmesi:
      başarı → {"success": True, "data": <API JSON>, "provider": "cloud", "model": ...}
      hata   → {"success": False, "model": ..., "error": ...}
    Anahtar hiçbir zaman hata metinlerinde döndürülmez.
    """
    mdl = (model or os.getenv("NEXUS_CLOUD_LLM_MODEL") or DEFAULT_MODEL).strip()
    base = normalized(base_url)
    anahtar = (key or "").strip()
    if not anahtar:
        return {"success": False, "model": mdl,
                "error": "Bulut model için API anahtarı verilmedi."}
    if not base:
        return {"success": False, "model": mdl,
                "error": "Bulut adresi geçersiz (yalnız https veya localhost)."}

    headers = {
        "Authorization": "Bearer " + anahtar,
        "Content-Type": "application/json",
        # OpenRouter hizalaması için (opsiyonel başlıklar):
        "HTTP-Referer": "https://nexus-core.local",
        "X-Title": "NEXUS-CORE",
    }
    payload: Dict[str, Any] = {
        "model": mdl,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice

    try:
        import httpx

        async with httpx.AsyncClient(
                timeout=timeout or cloud_timeout(),
                transport=transport,
                trust_env=False) as client:
            resp = await client.post(
                f"{base}/chat/completions", json=payload, headers=headers)
        if resp.status_code != 200:
            hata = resp.text[:300]
            return {"success": False, "model": mdl,
                    "error": f"Bulut model HTTP {resp.status_code}: {hata}"}
        data = resp.json()
    except Exception as exc:
        return {"success": False, "model": mdl,
                "error": f"Bulut bağlantı hatası: {type(exc).__name__}"}

    if not (data.get("choices") or []):
        return {"success": False, "model": mdl,
                "error": "Bulut model boş yanıt döndürdü."}

    # Reasoning modeli bazı uç noktalarda content yerine reasoning döndürür;
    # çağıran katman boş yanıt almasın diye reasoning metni içeriğe kopyalanır.
    try:
        mesaj = (data["choices"][0].get("message") or {})
        if not (mesaj.get("content") or "").strip():
            dusunme = (mesaj.get("reasoning") or data.get("reasoning") or
                       "").strip()
            if dusunme:
                mesaj["content"] = dusunme
    except Exception:
        pass

    return {"success": True, "data": data, "provider": "cloud", "model": mdl}


async def free_models(base_url: Optional[str] = None, limit: int = 12,
                      transport: Any = None) -> List[Dict[str, Any]]:
    """Sağlayıcının ücretsiz modellerini canlı listeler (anahtar GEREKMEZ).

    Ücretsiz model kimlikleri döner. Katalog sağlayıcıda sürekli değiştiği
    için (ör. z-ai/glm-5.2:free Eylül 2026'da kaldırılmıştı) liste her
    seferinde canlı çekilir ve UI'da kullanıcı güncel seçeneği görür.
    """
    base = normalized(base_url) or DEFAULT_BASE_URL
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15, trust_env=False,
                                     transport=transport) as client:
            resp = await client.get(f"{base}/models")
        if resp.status_code != 200:
            return []
        kayit = (resp.json().get("data") or [])
    except Exception:
        return []
    hepsi = []
    for m in kayit:
        mid = m.get("id") or ""
        if ":free" not in mid:
            continue
        hepsi.append({
            "id": mid,
            "ad": mid,
            "baglam": m.get("context_length") or 0,
        })
    # glm/z-ai önce, sonra alfabetik
    hepsi.sort(key=lambda m: (0 if "glm" in m["id"].lower() else 1, m["id"]))
    return hepsi[:limit]


async def glm_models(base_url: Optional[str] = None, limit: int = 12,
                     transport: Any = None) -> List[Dict[str, Any]]:
    """Sağlayıcının AKTİF GLM modellerini listeler (ücretsiz katman şart değil).

    OpenRouter'da ücretsiz (:free) GLM şu an bulunmayabilir; yerine
    kendi anahtarınla neredeyse bedava GLM-5.3 Flash gibi kimlikler
    kullanılabilir. Katman/batch tuhaf varyantlar listeye sonda düşer.
    """
    base = normalized(base_url) or DEFAULT_BASE_URL
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15, trust_env=False,
                                     transport=transport) as client:
            resp = await client.get(f"{base}/models")
        if resp.status_code != 200:
            return []
        kayit = resp.json().get("data") or []
    except Exception:
        return []
    hepsi = []
    for m in kayit:
        mid = m.get("id") or ""
        if "glm" not in mid.lower():
            continue
        fiyat = m.get("pricing") or {}
        # ":batch" ve "~" (esnek fiyat) varyantları standart sohbet için ikinciye
        ikincil = 1 if (":batch" in mid or mid.startswith("~")) else 0
        flash = 0 if "flash" in mid.lower() else 1
        # kullanıcının istediği 5.x kuşağı (ör. glm-5.3-flash) öne alınır
        kusak = 0 if "glm-5" in mid else 1
        hepsi.append({
            "id": mid,
            "ad": mid,
            "baglam": m.get("context_length") or 0,
            "girdi_fiyati": fiyat.get("prompt") or "",
            "cikti_fiyati": fiyat.get("completion") or "",
            "_sirala": (flash, kusak, ikincil, mid),
        })
    hepsi.sort(key=lambda m: m["_sirala"])
    for m in hepsi:
        del m["_sirala"]
    return hepsi[:limit]
