"""BYOK bulut kanalı testleri — HER KULLANICI KENDİ ANAHTARINI KULLANIR.

Kapsam:
- cloud_llm.chat sözleşmesi (local_llm.chat ile aynı biçim) + anahtarın
  Authorization başlığına gitmesi + reasoning → content devri
- hata yanıtlarının anahtarı SIZDIRMAMASI
- rota başlıkları (X-Nexus-Llm-Key/Model/Base) → llm_credential taşınması
- agent.chat temizliği: anahtar o çağrı sonunda instance'tan silinmelidir
- _call_local_primary: anahtarsız → yalnız yerel; anahtarlı → bulut önce;
  bulut başarısızsa yerel zincirde devam (yanıt HİÇ boş kalmaz)
- ücretsiz model listesi (glm öne alınır)
"""

import asyncio
from types import SimpleNamespace
from typing import Dict

import httpx

import ai_agent
import ai_agent_routes as routes
import cloud_llm
import local_llm


# ---------- yardımcılar ----------

class _Raw:
    """Rota'nın doğrudan test çağrısı için minimal istek sarıcısı."""

    def __init__(self, headers: Dict[str, str] = None):
        self.headers = dict(headers or {})


def _hafif_agent(**_ozellikler):
    """test_master_agents kalıbı: __init__ olmadan sentetik agent."""
    agent = ai_agent.NexusAIAgent.__new__(ai_agent.NexusAIAgent)
    agent.llm_config = ai_agent.LLMConfig(
        api_key="", base_url="http://127.0.0.1:11434/v1",
        model="qwen2.5:3b", temperature=0.2, max_tokens=128,
    )
    agent._tools_payload = lambda: []
    for ad, deger in _ozellikler.items():
        setattr(agent, ad, deger)
    return agent


# ---------- temel beceriler ----------

def test_mask_anahtari_gizler():
    assert cloud_llm.mask("sk-or-v1-abcdefgh1234") == "sk-or-***1234"
    assert cloud_llm.mask("") == ""
    assert cloud_llm.mask("kisa") == "kis***"


def test_base_url_kurallari():
    assert cloud_llm.normalized(None) == "https://openrouter.ai/api/v1"
    assert cloud_llm.normalized("https://api.z.ai/api/paas/v4/") == \
        "https://api.z.ai/api/paas/v4"
    # açık http yalnız localhost'a izinli
    assert cloud_llm.normalized("http://api.ornek.com/v1") is None
    assert cloud_llm.normalized("http://127.0.0.1:9999/v1") == \
        "http://127.0.0.1:9999/v1"
    assert cloud_llm.normalized("api.ornek.com") is None


# ---------- cloud_llm.chat sözleşmesi ----------

def test_cloud_chat_success_ve_yetkilendirme_basligi():
    yakalanan = {}

    def handler(_istek: httpx.Request) -> httpx.Response:
        yakalanan["auth"] = _istek.headers.get("authorization")
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "Merhaba!"}}],
        })

    sonuc = asyncio.run(cloud_llm.chat(
        [{"role": "user", "content": "selam"}], key="sk-test-1",
        model="z-ai/glm-4.5-air:free", transport=httpx.MockTransport(handler)))

    assert sonuc["success"] is True
    assert sonuc["provider"] == "cloud"
    assert sonuc["model"] == "z-ai/glm-4.5-air:free"
    assert sonuc["data"]["choices"][0]["message"]["content"] == "Merhaba!"
    # anahtar yalnız çağrı başlığında: local_llm sozlesmesi korunur
    assert yakalanan["auth"] == "Bearer sk-test-1"


def test_cloud_chat_reasoning_contente_devredilir():
    def handler(_istek: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "  ",
                                     "reasoning": "Adım 1, adım 2"}}],
        })

    sonuc = asyncio.run(cloud_llm.chat(
        [{"role": "user", "content": "selam"}], key="k",
        transport=httpx.MockTransport(handler)))

    mesaj = sonuc["data"]["choices"][0]["message"]
    assert mesaj["content"] == "Adım 1, adım 2"


def test_cloud_chat_hata_anahtari_sizdirmaz():
    def handler(_istek: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text='{"error": "Invalid credentials"}')

    sonuc = asyncio.run(cloud_llm.chat(
        [{"role": "user", "content": "selam"}], key="sk-gercek-anahtar",
        transport=httpx.MockTransport(handler)))

    assert sonuc["success"] is False
    assert "sk-gercek-anahtar" not in (sonuc.get("error") or "")
    assert "401" in sonuc["error"]


def test_anahtarsiz_bulut_cagrisi_reddedilir():
    sonuc = asyncio.run(cloud_llm.chat([{"role": "user", "content": "x"}], key="  "))
    assert sonuc["success"] is False


# ---------- rota başlıklarından taşınma ----------

def test_byok_basliklari_credential_olarak_tasinir(monkeypatch):
    yakalanan = {}

    async def fake_chat(message, conversation_id=None, history=None,
                        agent_id=None, tools_override=None,
                        system_prefix=None, current_user=None,
                        llm_credential=None):
        yakalanan["credential"] = llm_credential
        return {"success": True, "response": "ok", "conversation_id": "c1"}

    monkeypatch.setattr(routes, "chat", fake_chat)

    req = routes.ChatRequest(message="selam")
    yanit = asyncio.run(routes.chat_endpoint(
        req, raw_request=_Raw({
            "X-Nexus-Llm-Key": "sk-kullanici",
            "X-Nexus-Llm-Model": "z-ai/glm-4.5-air:free",
        }), current_user=None))

    cred = yakalanan["credential"]
    assert yanit.success is True
    assert cred["key"] == "sk-kullanici"
    assert cred["model"] == "z-ai/glm-4.5-air:free"
    assert cred["base_url"] is None


def test_key_basligi_yoksa_credential_none(monkeypatch):
    yakalanan = {}

    async def fake_chat(message, conversation_id=None, history=None,
                        agent_id=None, tools_override=None,
                        system_prefix=None, current_user=None,
                        llm_credential=None):
        yakalanan["credential"] = llm_credential
        return {"success": True, "response": "ok", "conversation_id": "c1"}

    monkeypatch.setattr(routes, "chat", fake_chat)

    yanit = asyncio.run(routes.chat_endpoint(
        routes.ChatRequest(message="selam"), raw_request=_Raw(),
        current_user=None))

    assert yanit.success is True
    assert yakalanan["credential"] is None


# ---------- agent zinciri: kirletici temizliği + kanal seçimi ----------

def test_modul_chat_anahtari_cagri_sonunda_siler(monkeypatch):
    agent = ai_agent.get_agent_v6()
    goruntulenen = {}

    async def fake_agent_chat(self, user_message, conversation_id=None,
                              history=None, agent_id=None,
                              tools_override=None, system_prefix=None,
                              current_user=None):
        goruntulenen["cred"] = getattr(agent, "_cloud_credential", None)
        return {"success": True, "response": "tamam", "conversation_id": "c"}

    monkeypatch.setattr(type(agent), "chat", fake_agent_chat)

    asyncio.run(ai_agent.chat("selam", llm_credential={"key": "sk-x", "model": None,
                                                      "base_url": None}))

    assert goruntulenen["cred"]["key"] == "sk-x"
    assert getattr(agent, "_cloud_credential", None) is None


def test_anahtarsiz_istek_yalniz_yereli_dener(monkeypatch):
    bulut_cagrilari = []

    async def cloud_izle(_m, **kw):
        bulut_cagrilari.append(kw)
        return {"success": True, "provider": "cloud", "model": "m", "data": {}}

    monkeypatch.setattr(cloud_llm, "chat", cloud_izle)

    async def local_ok(_m, **kw):
        return {"success": True, "model": "qwen2.5:3b",
                "data": {"choices": [{"message": {"content": "yerel"}}]}}

    monkeypatch.setattr(local_llm, "chat", local_ok)

    agent = _hafif_agent()  # _cloud_credential YOK
    sonuc = asyncio.run(agent._call_local_primary([{"role": "user", "content": "selam"}]))

    assert sonuc["provider"] == "local"
    assert not bulut_cagrilari


def test_anahtarli_istek_once_bulutu_dener(monkeypatch):
    async def cloud_ok(_m, **kw):
        return {"success": True, "provider": "cloud", "model": "z-ai/glm-4.5-air:free",
                "data": {"choices": [{"message": {"content": "bulut yanıtı"}}]}}

    monkeypatch.setattr(cloud_llm, "chat", cloud_ok)

    async def local_yasak(*_a, **_k):
        raise AssertionError("bulut başarılıyken yerel modele inilmemeli")

    monkeypatch.setattr(local_llm, "chat", local_yasak)

    agent = _hafif_agent(_cloud_credential={
        "key": "sk-k", "model": "z-ai/glm-4.5-air:free", "base_url": None})
    sonuc = asyncio.run(agent._call_local_primary([{"role": "user", "content": "selam"}]))

    assert sonuc["provider"] == "cloud"
    assert sonuc["data"]["choices"][0]["message"]["content"] == "bulut yanıtı"


def test_bulut_duserse_yerel_zincir_devam_eder(monkeypatch):
    async def cloud_fail(_m, **_kw):
        return {"success": False, "model": "m", "error": "Bulut HTTP 401: yetkisiz"}

    monkeypatch.setattr(cloud_llm, "chat", cloud_fail)

    async def local_ok(_m, **_kw):
        return {"success": True, "model": "qwen2.5:3b",
                "data": {"choices": [{"message": {"content": "yerel yanıt"}}]}}

    monkeypatch.setattr(local_llm, "chat", local_ok)

    agent = _hafif_agent(_cloud_credential={
        "key": "sk-k", "model": "m", "base_url": None})
    sonuc = asyncio.run(agent._call_local_primary([{"role": "user", "content": "selam"}]))

    # kritik: yanıt HİÇ boş kalmaz — bulut düşerken yerel doldurur
    assert sonuc["success"] is True
    assert sonuc["provider"] == "local"


# ---------- ücretsiz model listesi ----------

def test_glm_listesi_flash_once_siralir():
    def handler(_istek: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [
            {"id": "z-ai/glm-4.7-flash", "pricing": {"prompt": "0.0000000605"}},
            {"id": "z-ai/glm-5.2", "pricing": {"prompt": "0.000000006"}},
            {"id": "z-ai/glm-5.3-flash:batch", "pricing": {"prompt": "0.00000005"}},
            {"id": "z-ai/glm-5.3-flash", "pricing": {"prompt": "0.00000015"}},
            {"id": "~z-ai/glm-flash-latest", "pricing": {"prompt": "0.0000000285"}},
            {"id": "openai/gpt-4.1-mini", "pricing": {"prompt": "0.0000004"}},
        ]})

    liste = asyncio.run(cloud_llm.glm_models(
        transport=httpx.MockTransport(handler)))

    kimlikler = [m["id"] for m in liste]
    # kullanıcının istediği model mutlak başta; gpt elenir
    assert kimlikler[0] == "z-ai/glm-5.3-flash"
    assert "openai/gpt-4.1-mini" not in kimlikler
    # eski kuşak (4.7) ve tuhaf varyantlar (:batch, ~) flash'ın arkasında
    assert kimlikler.index("z-ai/glm-4.7-flash") > 0
    assert kimlikler.index("z-ai/glm-5.3-flash:batch") > 0

def test_ucretsiz_model_listesi_glm_once():
    def handler(_istek: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [
            {"id": "meta-llama/llama-3.3-70b:free", "context_length": 131072},
            {"id": "z-ai/glm-4.5-air:free", "context_length": 262144},
        ]})

    liste = asyncio.run(cloud_llm.free_models(
        transport=httpx.MockTransport(handler)))

    kimlikler = [m["id"] for m in liste]
    assert kimlikler == ["z-ai/glm-4.5-air:free", "meta-llama/llama-3.3-70b:free"]
    assert liste[0]["baglam"] == 262144


def test_ucretsiz_liste_yalniz_metin_yapani_alir():
    def handler(_istek: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [
            {"id": "a/gorunmez-embedding:free", "context_length": 8192,
             "architecture": {"output_modalities": ["embedding"]}},
            {"id": "b/sadece-resim:free", "context_length": 8192,
             "architecture": {"output_modalities": ["image"]}},
            {"id": "c/metin:free", "context_length": 8192,
             "architecture": {"output_modalities": ["text"]}},
        ]})

    liste = asyncio.run(cloud_llm.free_models(
        transport=httpx.MockTransport(handler)))
    assert [m["id"] for m in liste] == ["c/metin:free"]


def test_ucretsiz_model_listesi_hata_donusu_bos():
    def handler(_istek: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    liste = asyncio.run(cloud_llm.free_models(
        transport=httpx.MockTransport(handler)))
    assert liste == []


# ---------- rota: ücretsiz_model ucu ----------

def test_cloud_models_ucusu(monkeypatch):
    async def fake_free(base_url=None, limit=12, transport=None):
        return [{"id": "cohere/north-mini-code:free", "ad": "cohere/north-mini-code:free",
                 "baglam": 256000}]

    async def fake_glm(base_url=None, limit=12, transport=None):
        return [{"id": "z-ai/glm-5.3-flash", "ad": "z-ai/glm-5.3-flash",
                 "baglam": 128000, "girdi_fiyati": "0.00000015",
                 "cikti_fiyati": "0.0000005"}]

    monkeypatch.setattr(cloud_llm, "free_models", fake_free)
    monkeypatch.setattr(cloud_llm, "glm_models", fake_glm)

    yanit = asyncio.run(routes.cloud_models(_Raw()))
    assert yanit["success"] is True
    assert yanit["count"] == 1
    assert yanit["glm_count"] == 1
    assert yanit["glm"][0]["id"] == "z-ai/glm-5.3-flash"
