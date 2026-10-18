"""NEXUS-CORE backend başlatıcı.

Yerelde olduğu gibi dağıtımda (Docker / Render / Railway / Fly) da çalışır:
- Kendi dizinini kullanır (mutlak Windows yolu YOK).
- Port `PORT` ortam değişkeninden okunur (hosting platformları bunu atar).
"""
import os

import uvicorn

# Bu dosyanın bulunduğu klasörü çalışma dizini yap (göreli dosyalar için).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "0") == "1"
    uvicorn.run("app:app", host=host, port=port, reload=reload)
