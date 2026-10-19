"""
Sağlayıcı Sağlık Kaydı (in-memory devre kesici)
===============================================
NEDEN
-----
`_fallback_chain`, geçersiz anahtarlı bir sağlayıcının **tüm modellerini** tek tek
deniyordu. openrouter (17 model) + openai (5 model) 401 döndüğünde her sohbette
**22 gereksiz istek** atılıyordu. Bu, gecikmeyi onlarca saniye artırır ve logları
kirletir.

KURAL
-----
* **401/403** -> anahtar geçersiz: sağlayıcı tamamen devre dışı (30 dk).
* **404**     -> yalnızca o model yok (15 dk); kardeş modeller denenir.
* **429**     -> geçici: yalnızca o model beklemeye alınır (Retry-After, en çok 60 sn).
* **5xx / timeout / ağ hatası** -> durum DEĞİŞMEZ (geçici olabilir; yanlış karar yok).

GÜVENLİK
--------
Anahtar, istek gövdesi veya yanıt metni **saklanmaz**. Yalnızca HTTP durum kodu ve
kısa bir etiket tutulur; `snapshot()` çıktısı güvenle loglanabilir.

KALICILIK
---------
Bilinçli olarak **yalnızca bellek içi**: süreç yeniden başlayınca sıfırlanır.
Kullanıcı anahtarı panelden değiştirirse `/api-key` rotası `reset_provider()`
çağırır; böylece eski karar takılı kalmaz.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

INVALID_KEY_TTL = 1800.0      # 401/403 -> 30 dakika
MODEL_MISSING_TTL = 900.0     # 404 -> 15 dakika
DEFAULT_RATE_LIMIT_TTL = 60.0  # 429 -> en çok 60 saniye
MIN_RATE_LIMIT_TTL = 5.0


class ProviderHealth:
    """Süreç-yerel sağlayıcı/model sağlık durumu. İş parçacığı güvenli."""

    def __init__(self, clock: Optional[Callable[[], float]] = None) -> None:
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._providers: Dict[str, Dict[str, Any]] = {}
        self._models: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ iç
    @staticmethod
    def _model_key(provider: str, model: str) -> str:
        return f"{provider}/{model}"

    def _active(self, store: Dict[str, Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
        entry = store.get(key)
        if entry is None:
            return None
        if entry["until"] <= self._clock():
            store.pop(key, None)
            return None
        return entry

    def _remaining(self, entry: Dict[str, Any]) -> float:
        return round(max(0.0, entry["until"] - self._clock()), 1)

    # ------------------------------------------------------------- işaretle
    def mark_invalid(self, provider: str, status: int = 401,
                     ttl: float = INVALID_KEY_TTL) -> None:
        """Anahtar geçersiz (401/403): sağlayıcıyı tamamen devre dışı bırak."""
        now = self._clock()
        with self._lock:
            self._providers[provider] = {
                "state": "invalid_key",
                "status": int(status),
                "error": f"HTTP {status}",
                "at": now,
                "until": now + ttl,
            }

    def mark_model_missing(self, provider: str, model: str, status: int = 404,
                           ttl: float = MODEL_MISSING_TTL) -> None:
        """Model bulunamadı (404): yalnızca o modeli devre dışı bırak."""
        now = self._clock()
        with self._lock:
            self._models[self._model_key(provider, model)] = {
                "state": "model_missing",
                "status": int(status),
                "error": f"HTTP {status}",
                "at": now,
                "until": now + ttl,
            }

    def mark_rate_limited(self, provider: str, model: str,
                          wait: Optional[float] = None) -> None:
        """429: yalnızca o modeli kısa süre beklet (sağlayıcıyı kapatma)."""
        ttl = DEFAULT_RATE_LIMIT_TTL if wait is None else float(wait)
        ttl = max(MIN_RATE_LIMIT_TTL, min(ttl, DEFAULT_RATE_LIMIT_TTL))
        now = self._clock()
        with self._lock:
            self._models[self._model_key(provider, model)] = {
                "state": "rate_limited",
                "status": 429,
                "error": "HTTP 429",
                "at": now,
                "until": now + ttl,
            }

    def note_success(self, provider: str, model: Optional[str] = None) -> None:
        """Başarılı çağrı: sağlayıcı/model için önceki olumsuz kararı temizle."""
        with self._lock:
            self._providers.pop(provider, None)
            if model:
                self._models.pop(self._model_key(provider, model), None)

    # ---------------------------------------------------------------- sorgu
    def provider_blocked(self, provider: str) -> bool:
        with self._lock:
            entry = self._active(self._providers, provider)
            return bool(entry and entry["state"] == "invalid_key")

    def model_blocked(self, provider: str, model: str) -> bool:
        with self._lock:
            return self._active(self._models, self._model_key(provider, model)) is not None

    def cooldown_remaining(self, provider: str) -> float:
        with self._lock:
            entry = self._active(self._providers, provider)
            return self._remaining(entry) if entry else 0.0

    def provider_status(self, provider: str) -> Dict[str, Any]:
        with self._lock:
            entry = self._active(self._providers, provider)
            if entry is None:
                return {"status": "ok", "cooldown_seconds": 0.0}
            return {
                "status": entry["state"],
                "http": entry["status"],
                "error": entry["error"],
                "cooldown_seconds": self._remaining(entry),
            }

    def snapshot(self) -> Dict[str, Any]:
        """Süresi geçenleri temizleyip güvenli (sırsız) bir özet döndürür."""
        with self._lock:
            for store in (self._providers, self._models):
                for key in [k for k, v in store.items() if v["until"] <= self._clock()]:
                    store.pop(key, None)
            return {
                "blocked_providers": {
                    k: {
                        "state": v["state"],
                        "status": v["status"],
                        "error": v["error"],
                        "cooldown_seconds": self._remaining(v),
                    }
                    for k, v in self._providers.items()
                },
                "blocked_models": {
                    k: {
                        "state": v["state"],
                        "status": v["status"],
                        "error": v["error"],
                        "cooldown_seconds": self._remaining(v),
                    }
                    for k, v in self._models.items()
                },
            }

    # --------------------------------------------------------------- sıfırla
    def reset_provider(self, provider: str) -> None:
        """Anahtar değiştiğinde çağrılır: o sağlayıcıya ait tüm kararları sil."""
        with self._lock:
            self._providers.pop(provider, None)
            prefix = f"{provider}/"
            for key in [k for k in self._models if k.startswith(prefix)]:
                self._models.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._providers.clear()
            self._models.clear()


# Süreç genelinde tek örnek (ai_agent ve model_routes aynı durumu görür).
health = ProviderHealth()
