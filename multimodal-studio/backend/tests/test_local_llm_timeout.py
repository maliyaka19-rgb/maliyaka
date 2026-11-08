"""local_llm çağrı zaman aşımı — soğuk yükleme düzeltmesi testleri.

Arkaplan: model ilk çağrıda RAM'e yüklenirken 120 sn sınır pateledi ve
kullanıcı "LLM boş yanıt döndürdü" kibar hatası görüyordu. Sınır
artık NEXUS_LOCAL_LLM_TIMEOUT ile ayarlanabilir ve varsayılanı 300 sn.
"""
import importlib

import local_llm


def test_varsayilan_zamanasimi_soguk_yuklemeye_yeter():
    assert local_llm.CHAT_TIMEOUT >= 240.0


def test_env_ile_ayarlanabilir(monkeypatch):
    monkeypatch.setenv("NEXUS_LOCAL_LLM_TIMEOUT", "777")
    try:
        yeni = importlib.reload(local_llm)
        assert yeni.CHAT_TIMEOUT == 777.0
    finally:
        monkeypatch.delenv("NEXUS_LOCAL_LLM_TIMEOUT", raising=False)
        importlib.reload(local_llm)
