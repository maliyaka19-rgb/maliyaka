"""RAG lazy-import koruma testi (G3 optimizasyonu).

Amaç: `import rag_system` ağır bağımlılıkları (sentence_transformers/torch/chromadb)
modül yüklemesinde ÇEKMEMELİ. Bu, `import ai_agent` süresini ~28s'den ~4s'ye indirdi.

Subprocess kullanılır çünkü sys.modules durumu diğer testlerden etkilenebilir.
"""
import subprocess
import sys
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(code: str) -> str:
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=BACKEND_DIR, timeout=120,
    )
    assert r.returncode == 0, f"subprocess hata: {r.stderr[-500:]}"
    return r.stdout.strip()


def test_rag_import_does_not_load_heavy_deps():
    out = _run(
        "import sys, rag_system; "
        "print('heavy' if any(m in sys.modules for m in "
        "('sentence_transformers','torch','chromadb')) else 'light')"
    )
    assert out == "light", f"rag_system ağır bağımlılık çekiyor: {out}"


def test_rag_availability_flags_are_booleans():
    out = _run(
        "import rag_system; "
        "print(type(rag_system.CHROMA_AVAILABLE).__name__, type(rag_system.ST_AVAILABLE).__name__)"
    )
    assert out == "bool bool", out


def test_ai_agent_import_is_fast():
    """`import ai_agent` makul sürede (<10s) tamamlanmalı (regresyon koruması)."""
    import time
    code = (
        "import time, sys; "
        "sys.path.insert(0, '.'); "
        "t=time.time(); import ai_agent; "
        "print(round(time.time()-t, 2))"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=BACKEND_DIR, timeout=120,
    )
    assert r.returncode == 0, r.stderr[-500:]
    elapsed = float(r.stdout.strip().splitlines()[-1])
    assert elapsed < 10.0, f"import ai_agent çok yavaş: {elapsed}s"
