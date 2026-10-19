"""
Ortak test yapılandırması.

ÖNEMLİ: `provider_health.health` süreç-yerel (global) bir devre kesicidir.
Bir testte 401 alıp sağlayıcıyı devre dışı bırakmak, sonraki testlerin
davranışını sessizce değiştirir (test kirliliği). Bu yüzden her testten önce
ve sonra sıfırlanır.
"""

import pytest

from provider_health import health

# Testler GERÇEK çalışma verisini yazmamalı (hermetik test kuralı).
# Otomatik içgörü üretimi varsayılan AÇIK; testlerde kapatılır.
# Bunu özellikle test eden dosya `monkeypatch.setenv` ile açar.
import os as _os

_os.environ.setdefault("NEXUS_AUTO_INSIGHTS", "0")


@pytest.fixture(autouse=True)
def reset_provider_health():
    health.reset()
    yield
    health.reset()
