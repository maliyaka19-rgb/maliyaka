"""
Telegram Bot Integration (long-polling)
=======================================
Kendi kendine yeten, harici kütüphane gerektirmeyen Telegram botu.
Telegram Bot API'sine doğrudan ``httpx`` üzerinden bağlanır.

Tasarım notları:
- ``ai_agent`` ve ``custom_agents`` modülleri ağır oldukları için yalnızca
  kullanıldıkları fonksiyonların içinde (lazy) içe aktarılır.
- Token asla loglanmaz / döndürülmez; sadece şifreli olarak saklanır.
- Test edilebilirlik için API taban adresi ``TELEGRAM_API_BASE`` ortam
  değişkeninden okunur ve isteğe bağlı olarak ``httpx.AsyncClient`` enjekte
  edilebilir.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

# ---------------------------------------------------------------------------
# Sabitler / yapılandırma
# ---------------------------------------------------------------------------

# Ayar dosyası (modülün yanında)
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_config.json")

# Telegram API taban adresi (testlerde override edilebilir)
API_BASE = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")

# Tek bir Telegram mesajı için güvenli üst sınır (API limiti 4096; pay bırakıyoruz)
MAX_MESSAGE_LEN = 4000

# Uzun polling süresi (saniye)
POLL_TIMEOUT = 30

# Ağ hatalarında bekleme süresi (saniye)
ERROR_SLEEP = 3.0

# Yetkisiz kullanıcıya gönderilen kısa mesaj
UNAUTHORIZED_TEXT = "⛔ Yetkisiz kullanıcı. Bu bottan yararlanma izniniz yok."

HELP_TEXT = """🤖 NEXUS-CORE Telegram Botu

Komutlar:
/start veya /help — Bu yardım mesajını gösterir
/new — Yeni bir sohbet başlatır
/reset — Sohbeti sıfırlar (yeni sohbet)
/agents — Kullanılabilir ajanları listeler
/agent <id> — Bu sohbet için ajan seçer
/status — Bot / model durumunu gösterir
/id — Telegram sohbet kimliğinizi gösterir

Herhangi bir mesaj yazın; seçili ajan size yanıt verir."""


# ---------------------------------------------------------------------------
# Şifreleme yardımcıları (model_routes ile uyumlu, fallback'li)
# ---------------------------------------------------------------------------

def _try_encrypt(token: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Token'ı şifreler ve (alan_adı, değer) döndürür.

    ``model_routes`` içe aktarılamazsa düz metin ``token`` alanına düşer.
    """
    if not token:
        return None, None
    try:
        from model_routes import _encrypt_key  # lazy import

        return "token_enc", _encrypt_key(token)
    except Exception:
        return "token", token


def _try_decrypt(cfg: Dict[str, Any]) -> str:
    """Ayar sözlüğünden token'ı çözer; şifreli veya düz metin olabilir."""
    if cfg.get("token_enc"):
        try:
            from model_routes import _decrypt_key  # lazy import

            return _decrypt_key(cfg["token_enc"]) or ""
        except Exception:
            return ""
    return cfg.get("token") or ""


def _normalize_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Bilinmeyen alanları temizler ve değer tiplerini düzeltir."""
    cfg: Dict[str, Any] = {
        "allowed_chat_ids": [],
        "enabled": bool(config.get("enabled", False)),
        "default_agent_id": (config.get("default_agent_id") or "auto"),
    }

    raw_ids = config.get("allowed_chat_ids") or []
    ids: List[int] = []
    for value in raw_ids:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    cfg["allowed_chat_ids"] = ids

    if config.get("token_enc"):
        cfg["token_enc"] = config["token_enc"]
    elif config.get("token"):
        cfg["token"] = config["token"]

    return cfg


def load_config() -> dict:
    """
    Ayar dosyasını okur ve normalize edilmiş sözlük döndürür.

    Dikkat: döndürülen sözlük şifreli ``token_enc`` (veya fallback ``token``)
    içerebilir; dışarıya (API/log) verilmemelidir. Ham token için
    ``_try_decrypt`` kullanılır.
    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return _normalize_config(data)
        except Exception:
            pass
    return {"allowed_chat_ids": [], "enabled": False, "default_agent_id": "auto"}


def save_config(config: dict) -> dict:
    """
    Ayar dosyasını yazar. Düz metin ``token`` verilmişse (ve henüz şifreli
    değilse) ``model_routes._encrypt_key`` ile şifreleyip ``token_enc`` alanına
    taşır. Şifreleme mümkün değilse düz metin ``token`` alanında bırakır.
    """
    cfg = _normalize_config(config)

    plain = config.get("token")
    if plain and not config.get("token_enc"):
        field, value = _try_encrypt(plain)
        if field and value:
            cfg.pop("token", None)
            cfg[field] = value

    directory = os.path.dirname(CONFIG_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    return cfg


def token_is_set() -> bool:
    """Ayar dosyasında token olup olmadığını (şifreli veya düz) döndürür."""
    cfg = load_config()
    return bool(cfg.get("token_enc") or cfg.get("token"))


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def parse_command(text: str) -> Tuple[str, str]:
    """
    ``"/agent coder"`` -> ``("/agent", "coder")``
    ``"/start"``        -> ``("/start", "")``
    ``"hello"``         -> ``("", "hello")``
    Komut adı küçük harfe çevrilir ve ``@botname`` eki soyulur.
    """
    if not text:
        return "", ""
    text = text.strip()
    if not text.startswith("/"):
        return "", text
    parts = text.split(None, 1)
    command = parts[0].split("@", 1)[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    return command, args


def split_message(text: str, limit: int = MAX_MESSAGE_LEN) -> List[str]:
    """
    Metni <= ``limit`` karakterlik parçalara böler; mümkünse paragraf/satır
    sınırlarında keser. Boş G/Ç durumunda ``[""]`` yerine ``[]`` dönebilir.
    """
    text = text or ""
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        idx = window.rfind("\n\n")
        if idx < limit // 2:
            idx = window.rfind("\n")
        if idx < limit // 2:
            idx = window.rfind(" ")
        if idx <= 0:
            idx = limit
        chunks.append(remaining[:idx].strip("\n"))
        remaining = remaining[idx:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return [c for c in chunks if c]


def _model_info() -> Tuple[Optional[str], Optional[str]]:
    """Aktif sağlayıcı/model bilgisini (best-effort) döndürür."""
    try:
        from model_routes import _load_config  # lazy import

        cfg = _load_config()
        return cfg.get("active_provider"), cfg.get("active_model")
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class TelegramBot:
    """Uzun polling tabanlı Telegram botu."""

    def __init__(
        self,
        token: str,
        allowed_chat_ids: Optional[List[int]] = None,
        default_agent_id: str = "auto",
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.token = token or ""
        self.allowed_chat_ids: List[int] = [int(x) for x in (allowed_chat_ids or [])]
        self.default_agent_id = default_agent_id or "auto"

        # Enjekte edilen istemci testlerde MockTransport ile verilir.
        self._client: Optional[httpx.AsyncClient] = client
        self._own_client: bool = client is None

        self.running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._offset: int = 0
        self._api_base: str = os.getenv("TELEGRAM_API_BASE", API_BASE).rstrip("/")

        # {chat_id: {"conv_id": str, "agent_id": str, "counter": int}}
        self._chats: Dict[int, Dict[str, Any]] = {}
        self.bot_username: Optional[str] = None

    # -- HTTP / URL ---------------------------------------------------------

    def _url(self, method: str) -> str:
        return f"{self._api_base}/bot{self.token}/{method}"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(POLL_TIMEOUT + 10.0, connect=15.0)
            )
            self._own_client = True
        return self._client

    # -- Yaşam döngüsü ------------------------------------------------------

    async def start(self) -> None:
        """Polling görevini başlatır."""
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._poll_loop())
        try:
            await self._refresh_me()
        except Exception:
            # getMe başarısız olsa bile polling devam eder.
            pass

    async def stop(self) -> None:
        """Polling görevini ve (sahiplenilmişse) istemciyi temiz kapatır."""
        self.running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._own_client and self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def _refresh_me(self) -> None:
        """Bot kullanıcı adını getMe ile (best-effort) alır."""
        client = await self._get_client()
        resp = await client.get(self._url("getMe"))
        data = resp.json()
        if data.get("ok"):
            result = data.get("result") or {}
            self.bot_username = result.get("username")

    # -- Polling ------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """getUpdates ile uzun polling. Hata döngüyü asla öldürmez."""
        while self.running:
            try:
                client = await self._get_client()
                resp = await client.get(
                    self._url("getUpdates"),
                    params={
                        "offset": self._offset,
                        "timeout": POLL_TIMEOUT,
                        "allowed_updates": json.dumps(["message"]),
                    },
                )
                data = resp.json()
                if not data.get("ok"):
                    await asyncio.sleep(ERROR_SLEEP)
                    continue
                for update in data.get("result", []) or []:
                    try:
                        update_id = update.get("update_id")
                        if isinstance(update_id, int):
                            self._offset = max(self._offset, update_id + 1)
                        await self._handle_update(update)
                    except Exception:
                        # Tek bir update hatası döngüyü durdurmaz.
                        continue
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(ERROR_SLEEP)

    # -- Update işleme ------------------------------------------------------

    async def _handle_update(self, update: Dict[str, Any]) -> None:
        """Bir Telegram update'ini işler; allowlist ve komut yönlendirmesi yapar."""
        message = update.get("message") or {}
        text = message.get("text")
        chat = message.get("chat") or {}
        chat_id = chat.get("id")

        if chat_id is None or not text:
            return
        chat_id = int(chat_id)

        # Allowlist: boş değilse ve chat id listede yoksa reddet.
        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            await self.send_message(chat_id, UNAUTHORIZED_TEXT)
            return

        await self._dispatch(chat_id, text)

    async def _dispatch(self, chat_id: int, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if text.startswith("/"):
            command, args = parse_command(text)
            await self._handle_command(chat_id, command, args)
        else:
            await self._handle_text(chat_id, text)

    # -- Sohbet durumu ------------------------------------------------------

    def _new_conversation(self, chat_id: int) -> str:
        state = self._chats.setdefault(chat_id, {})
        counter = int(state.get("counter", 1)) + 1
        state["counter"] = counter
        conv_id = f"tg_{chat_id}_{counter}"
        state["conv_id"] = conv_id
        return conv_id

    def _state(self, chat_id: int) -> Dict[str, Any]:
        state = self._chats.setdefault(chat_id, {})
        if "counter" not in state:
            state["counter"] = 1
        if "conv_id" not in state:
            state["conv_id"] = f"tg_{chat_id}_{state['counter']}"
        if "agent_id" not in state:
            state["agent_id"] = self.default_agent_id
        return state

    # -- Komutlar -----------------------------------------------------------

    async def _handle_command(self, chat_id: int, command: str, args: str) -> None:
        if command in ("/start", "/help"):
            await self.send_message(chat_id, HELP_TEXT)
        elif command in ("/new", "/reset"):
            conv_id = self._new_conversation(chat_id)
            await self.send_message(
                chat_id,
                "🆕 Yeni sohbet başlatıldı.\n"
                f"Sohbet kimliği: {conv_id}",
            )
        elif command == "/agents":
            await self.send_message(chat_id, self._agents_text())
        elif command == "/agent":
            await self._set_agent(chat_id, args)
        elif command == "/status":
            await self.send_message(chat_id, self._status_text(chat_id))
        elif command == "/id":
            await self.send_message(chat_id, f"🆔 Sohbet kimliğiniz: {chat_id}")
        else:
            await self.send_message(
                chat_id,
                f"❓ Bilinmeyen komut: {command}\n"
                "/help yazarak kullanılabilir komutları görebilirsiniz.",
            )

    def _agents_text(self) -> str:
        try:
            from custom_agents import load_agents  # lazy import

            agents = load_agents() or []
        except Exception:
            agents = []
        if not agents:
            return "⚠️ Kayıtlı ajan bulunamadı."
        lines = ["🤖 Kullanılabilir ajanlar:"]
        for agent in agents:
            lines.append(f"• {agent.get('id', '?')} — {agent.get('name', '')}")
        lines.append("\nSeçmek için: /agent <id>")
        return "\n".join(lines)

    async def _set_agent(self, chat_id: int, args: str) -> None:
        agent_id = (args or "").strip()
        if not agent_id:
            await self.send_message(
                chat_id, "Kullanım: /agent <id>\nAjanları görmek için /agents yazın."
            )
            return
        try:
            from custom_agents import get_agent  # lazy import

            agent = get_agent(agent_id)
        except Exception:
            agent = None
        if not agent:
            await self.send_message(
                chat_id,
                f"⚠️ '{agent_id}' adlı ajan bulunamadı. /agents ile listeyi görebilirsiniz.",
            )
            return
        state = self._state(chat_id)
        state["agent_id"] = agent_id
        name = agent.get("name", "") if isinstance(agent, dict) else ""
        await self.send_message(chat_id, f"✅ Ajan ayarlandı: {agent_id} — {name}".rstrip(" —"))

    def _status_text(self, chat_id: int) -> str:
        state = self._state(chat_id)
        provider, model = _model_info()
        return (
            "📊 Durum\n"
            f"• Bot: {'çalışıyor' if self.running else 'durdu'}\n"
            f"• Ajan: {state.get('agent_id', self.default_agent_id)}\n"
            f"• Sohbet: {state.get('conv_id', '-')}\n"
            f"• Model: {provider or '-'} / {model or '-'}"
        )

    # -- Serbest metin (ajana gönderim) -------------------------------------

    async def _handle_text(self, chat_id: int, text: str) -> None:
        state = self._state(chat_id)
        agent_id = state.get("agent_id") or self.default_agent_id
        if agent_id in (None, "", "auto"):
            agent_id = None  # ajanın otomatik seçmesine izin ver

        try:
            import ai_agent  # lazy import (ağır)

            result = await ai_agent.chat(
                text,
                conversation_id=state.get("conv_id"),
                agent_id=agent_id,
            )
        except Exception:
            await self.send_message(
                chat_id,
                "⚠️ Üzgünüm, bir hata oluştu. Lütfen tekrar deneyin.",
            )
            return

        result = result or {}
        if result.get("success"):
            reply = result.get("response") or "(boş yanıt)"
            tools = result.get("tools_used") or []
            if tools:
                reply = f"{reply}\n\n🔧 {len(tools)} araç kullanıldı."
            await self.send_message(chat_id, reply)
        else:
            error = result.get("response") or result.get("error") or "Bilinmeyen hata"
            await self.send_message(chat_id, f"⚠️ İşlem tamamlanamadı: {error}")

    # -- Mesaj gönderme -----------------------------------------------------

    async def send_message(self, chat_id: int, text: str) -> None:
        """Mesajı <= 4000 karakterlik parçalara bölerek gönderir."""
        chunks = split_message(text)
        if not chunks:
            return
        client = await self._get_client()
        for chunk in chunks:
            try:
                await client.post(
                    self._url("sendMessage"),
                    json={"chat_id": chat_id, "text": chunk},
                )
            except Exception:
                # Tek bir parça gönderilemezse diğerlerini denemeye devam et.
                continue

    # -- Durum --------------------------------------------------------------

    def status(self) -> dict:
        """Ham token'ı içermeyen durum özeti."""
        return {
            "running": bool(self.running),
            "allowed_chat_ids": list(self.allowed_chat_ids),
            "default_agent_id": self.default_agent_id,
            "chat_count": len(self._chats),
        }


# ---------------------------------------------------------------------------
# Modül düzeyi tekil (singleton) yönetimi
# ---------------------------------------------------------------------------

_bot: Optional[TelegramBot] = None


def get_bot() -> Optional[TelegramBot]:
    """Aktif bot örneğini (varsa) döndürür."""
    return _bot


async def start_bot_from_config() -> dict:
    """
    Kayıtlı ayarlardan botu başlatır. Token yoksa ``ValueError`` yükseltir.
    """
    global _bot
    cfg = load_config()
    token = _try_decrypt(cfg)
    if not token:
        raise ValueError("Telegram token yapılandırılmamış.")

    if _bot is not None and _bot.running:
        await _bot.stop()

    _bot = TelegramBot(
        token,
        allowed_chat_ids=cfg.get("allowed_chat_ids") or [],
        default_agent_id=cfg.get("default_agent_id") or "auto",
    )
    await _bot.start()
    return _bot.status()


async def stop_bot() -> None:
    """Çalışan botu (varsa) durdurur."""
    global _bot
    if _bot is not None:
        await _bot.stop()
