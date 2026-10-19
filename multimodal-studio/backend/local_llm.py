"""
Yerel Model Yedekliligi (Local LLM fallback)
===========================================
OpenAI-uyumlu yerel sunuculari (Ollama, LM Studio, llama.cpp) tespit eder ve
gerektiginde **yedek saglayici** olarak kullanir.

NEDEN
-----
Tek bulut saglayicisina bagimlilik risklidir (kota/TPM limiti, ag kesintisi,
hesap/anahtar sorunu). Yerel bir model bu durumlar icin bağımsız bir yedektir.

DURUM (dürüst not)
------------------
Bu makinede kurulu yerel calisma zamani YOK (ollama/lms/llama-server bulunamadi)
ve donanim zayif (i5-5200U, ~8GB RAM, GeForce 940M 2GB). Kod yolu ve tespit
GERCEKTIR ve test edilmistir; ancak gercek model agirliklari icin Ollama/LM Studio
KURULMALIDIR. Kurulum olmadan bu katman devre disidir ve hicbir sey bozulmaz.

GUVENLIK
--------
* Yalnizca **loopback** adreslerine (127.0.0.1 / localhost / [::1]) baglanir.
* API anahtari GEREKMEZ; hicbir sir okunmaz/yazilmaz.
* **Varsayilan KAPALI**: ``NEXUS_LOCAL_LLM_URL`` tanimli degilse hicbir ag
  cagrisi yapilmaz (mevcut davranis degismez).

Etkinlestirme::

    set NEXUS_LOCAL_LLM_URL=http://127.0.0.1:11434/v1     # Ollama
    set NEXUS_LOCAL_LLM_MODEL=qwen2.5:1.5b                # (opsiyonel)

Kucuk donanim icin onerilen modeller: ``qwen2.5:0.5b``, ``qwen2.5:1.5b``,
``llama3.2:1b``, ``llama3.2:3b`` (Q4).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

ENV_URL = "NEXUS_LOCAL_LLM_URL"
ENV_MODEL = "NEXUS_LOCAL_LLM_MODEL"

# (calisma zamani adi, OpenAI-uyumlu base_url)
CANDIDATE_ENDPOINTS: List[tuple] = [
    ("ollama", "http://127.0.0.1:11434/v1"),
    ("lmstudio", "http://127.0.0.1:1234/v1"),
    ("llamacpp", "http://127.0.0.1:8080/v1"),
]

DETECT_TIMEOUT = 1.5
CHAT_TIMEOUT = 120.0

# Kucuk donanimda gercekci (Q4) oneriler; bilgilendirme amaclidir.
RECOMMENDED_MODELS = ["qwen2.5:0.5b", "qwen2.5:1.5b", "llama3.2:1b", "llama3.2:3b"]


# ============================================================
# AYARLAR / GUVENLIK
# ============================================================

def configured_url() -> str:
    return (os.getenv(ENV_URL) or "").strip().rstrip("/")


def model_name() -> str:
    return (os.getenv(ENV_MODEL) or "").strip()


def is_loopback(url: str) -> bool:
    """Yalnizca yerel adreslere izin ver (SSRF korumasi)."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def is_enabled() -> bool:
    """Yerel yedek yalnizca gecerli bir loopback URL tanimliysa etkindir."""
    url = configured_url()
    return bool(url) and is_loopback(url)


def status_note() -> str:
    if not configured_url():
        return "Yerel model KAPALI (NEXUS_LOCAL_LLM_URL tanimli degil)."
    if not is_loopback(configured_url()):
        return "Yerel model KAPALI: yalnizca loopback (127.0.0.1/localhost) adresleri desteklenir."
    return f"Yerel model ACIK: {configured_url()}"


# ============================================================
# TESPIT
# ============================================================

async def _list_models(base_url: str, timeout: float) -> List[str]:
    import httpx

    # trust_env=False: yerel cagrilar ortam proxy'lerinden ETKILENMESIN.
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        resp = await client.get(f"{base_url}/models")
        if resp.status_code != 200:
            return []
        data = resp.json()
    items = data.get("data") if isinstance(data, dict) else None
    return [m["id"] for m in (items or []) if isinstance(m, dict) and m.get("id")]


async def _probe(runtime: str, base_url: str, timeout: float) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"runtime": runtime, "base_url": base_url}
    if not is_loopback(base_url):
        entry.update({"ok": False, "error": "loopback degil (guvenlik)"})
        return entry
    try:
        entry.update({"ok": True, "models": await _list_models(base_url, timeout)})
    except Exception as exc:
        entry.update({"ok": False, "error": type(exc).__name__})
    return entry


def _usable(entry: Dict[str, Any]) -> bool:
    return bool(entry.get("ok")) and (bool(entry.get("models")) or entry.get("runtime") == "env")


async def detect(timeout: float = DETECT_TIMEOUT) -> Dict[str, Any]:
    """
    Calisan OpenAI-uyumlu yerel sunucuyu bulur. Hicbiri yoksa guvenli sekilde
    ``available=False`` doner (istisna firlatmaz). Sondalamalar PARALEL yapilir.
    """
    checked: List[Dict[str, Any]] = []

    # 1) Kullanici acikca URL verdiyse once onu dene (hizli yol).
    override = configured_url()
    if override:
        entry = await _probe("env", override, timeout)
        checked.append(entry)
        if _usable(entry):
            return {"available": True, "runtime": "env", "base_url": entry["base_url"],
                    "models": entry.get("models", []), "checked": checked}

    # 2) Bilinen calisma zamanlarini PARALEL yokla.
    results = await asyncio.gather(
        *(_probe(name, base, timeout) for name, base in CANDIDATE_ENDPOINTS)
    )
    checked.extend(results)
    for entry in results:
        if _usable(entry):
            return {"available": True, "runtime": entry["runtime"],
                    "base_url": entry["base_url"], "models": entry.get("models", []),
                    "checked": checked}

    return {"available": False, "runtime": None, "base_url": None,
            "models": [], "checked": checked}


# ============================================================
# KULLANIM (yerel yedek cagrisi)
# ============================================================

async def chat(messages: List[Dict[str, Any]], model: Optional[str] = None,
               base_url: Optional[str] = None, temperature: float = 0.7,
               max_tokens: int = 1024, timeout: float = CHAT_TIMEOUT) -> Dict[str, Any]:
    """
    Yerel OpenAI-uyumlu ``/chat/completions`` cagrisi. Bulut saglayicilarla ayni
    sekli dondurur: basarida ``{"success": True, "data": {...}}``.

    NOT: Yerel/kucuk modellere arac (tools) semasi GONDERILMEZ; metin yaniti
    uretirler. Bu, arac cagrisi gerektiren gorevlerde bilincli bir sinirlamadir.
    """
    base = (base_url or configured_url()).rstrip("/")
    if not base:
        return {"success": False, "error": "Yerel model URL tanimli degil "
                                           f"({ENV_URL})."}
    if not is_loopback(base):
        return {"success": False, "error": "Guvenlik: yalnizca localhost adresleri desteklenir."}

    mdl = (model or model_name() or "").strip()
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            if not mdl:
                models = await _list_models(base, 5.0)
                if not models:
                    return {"success": False,
                            "error": "Yerel sunucuda kullanilabilir model bulunamadi."}
                mdl = models[0]
            payload = {
                "model": mdl,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            resp = await client.post(f"{base}/chat/completions", json=payload)
            if resp.status_code != 200:
                return {"success": False, "model": mdl,
                        "error": f"Yerel model HTTP {resp.status_code}: {resp.text[:200]}"}
            data = resp.json()
    except Exception as exc:
        return {"success": False, "model": mdl,
                "error": f"Yerel model baglanti hatasi: {exc}"}

    return {"success": True, "data": data, "provider": "local",
            "model": mdl, "local": True}
