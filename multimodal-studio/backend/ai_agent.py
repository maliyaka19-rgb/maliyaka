"""
NEXUS-CORE v6.1 - TRUE AI AGENT
================================
Real AI Agent with LLM reasoning, tool use, and conversation memory.
Works like ChatGPT but with specialized multimodal tools.

Architecture:
- LLM Core: OpenRouter or local OpenAI-compatible server (Ollama/LM Studio)
- Tools: Code Gen, Visual Gen, Video Gen, Web Search, Learning
- Memory: Conversation history + Long-term learning
- Agent Loop: Plan → Act → Observe → Reflect
"""

import json
import time
import uuid
import os
import re
import py_compile  # _self_review: Python dosyalarını derle-denetle
import socket
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from collections import deque
import logging
import asyncio
import httpx
from contextvars import ContextVar

# Sağlayıcı devre kesici: 401/403 alan sağlayıcıyı her sohbette yeniden denemeyi
# önler (geçersiz anahtarla 22 gereksiz istek atılıyordu).
from provider_health import health

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# OpenAI SDK (or any compatible LLM API)
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

logger = logging.getLogger("nexus-agent-v6")

# İstek-yerel (request-local) ajan durumu. Ajan tekil (singleton) olsa da her
# asyncio görevi kendi context kopyasını taşır; eşzamanlı iki sohbet birbirinin
# araç iznini/modelini EZMEZ. (Önceden instance attribute idi -> yarış vardı.)
_ACTIVE_TOOLS: ContextVar[Optional[list]] = ContextVar("nexus_active_tools", default=None)
_ACTIVE_MODEL: ContextVar[Optional[str]] = ContextVar("nexus_active_model", default=None)

# Import Brain
from brain import get_brain, NexusBrain

# Import RAG System
try:
    from rag_system import rag_add_document, rag_search, rag_list_documents, rag_delete_document, rag_get_stats
    RAG_AVAILABLE = True
except ImportError as e:
    logger.warning(f"RAG system not available: {e}")
    RAG_AVAILABLE = False


# ---- Modular components (Phase 3.2) ----
from web_tools import SafeCalculator, web_search_duckduckgo, web_search_serpapi, web_search_unified
from tools_spec import TOOLS
from memory import Message, Conversation, ConversationMemory, LearningMemory
from tool_executor import ToolExecutor

# ============================================================
# LLM CONFIGURATION
# ============================================================

@dataclass
class LLMConfig:
    """LLM provider configuration."""
    provider: str = "openrouter"  # openrouter, local
    model: str = "inclusionai/ling-3.0-flash-fin"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    streaming: bool = False


# ============================================================
# TOOL DEFINITIONS (Function Calling Format)
# ============================================================

# These are the tools available to the LLM

# ============================================================
# MAIN AI AGENT (LLM-POWERED)
# ============================================================

def _validate_response(data: Dict) -> bool:
    """Validate LLM response structure. Returns True if valid."""
    try:
        if not isinstance(data, dict):
            return False
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) == 0:
            return False
        for choice in choices:
            if not isinstance(choice, dict):
                return False
            message = choice.get("message")
            if not isinstance(message, dict):
                return False
            if message.get("role") != "assistant":
                return False
            # tool_calls validation if present
            tool_calls = message.get("tool_calls")
            # OpenAI-uyumlu sağlayıcılar, asistan yalnızca
            # araç çağrısı ürettiğinde "content" alanını tamamen atlar (null bile
            # göndermez). Bu GEÇERLİ bir yanıttır → content veya tool_calls'ten en
            # az biri bulunmalıdır. (Aksi halde geçerli araç çağrıları reddedilip
            # gereksiz fallback zinciri tetikleniyordu.)
            if tool_calls is None and "content" not in message:
                return False
            if tool_calls is not None:
                if not isinstance(tool_calls, list):
                    return False
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        return False
                    if tc.get("type") != "function":
                        return False
                    func = tc.get("function")
                    if not isinstance(func, dict):
                        return False
                    if not isinstance(func.get("name"), str) or not isinstance(func.get("arguments"), str):
                        return False
        return True
    except Exception:
        return False


# How many times to retry the SAME provider/model after a 429 (rate limit)
# before falling back to other models/providers.
# Dusuk tut: uzun bekleme yerine fallback zinciri (diger modeller/saglayicilar) calsin.
_RATE_LIMIT_MAX_RETRIES = 1
_MAX_RATE_LIMIT_WAIT = 5.0  # saniye - Retry-After uzun donse bile kisitla


# ============================================================
# YEREL MODEL ARAÇ ÇAĞRISI AYIKLAMA (birden çok JSON nesnesi)
# ============================================================

_JSON_DECODER = json.JSONDecoder()

try:
    import unicodedata as _unicodedata
except Exception:  # pragma: no cover
    _unicodedata = None


def _norm_tr(text: str) -> str:
    """Türkçe-dostu küçük harf normalizasyonu.

    Python'un ``str.lower`` çıktısı "İ" için 'i̇' (i + birleştirici nokta)
    üretir; This breaks ``"site" in q`` gibi düz metin eşleşmeleri. Burada
    birleştirici noktalar soyulur.
    """
    s = (text or "").lower()
    if _unicodedata is not None:
        s = _unicodedata.normalize("NFKC", s)
        s = "".join(c for c in s if not _unicodedata.combining(c))
    return s.replace("i\u0307", "i")


# Tam ASCII dönüşümü: şablon yönlendirici gibi TÜM diyalekt yazımları
# ("öğrenci"/"ogrenci", "kahvaltı"/"kahvalti") tek çizgiye indirir.
_ASCII_TR_TABLE = str.maketrans({
    "ö": "o", "ğ": "g", "ü": "u", "ş": "s", "ç": "c", "ı": "i",
    "â": "a", "î": "i", "û": "u",
})


def _ascii_tr(text: str) -> str:
    """Diakritik tamamen soyulmuş (ö->o, ğ->g …) normalize metin."""
    return _norm_tr(text).translate(_ASCII_TR_TABLE)


def _extract_tool_json_calls(text: str, allowed_names):
    """Metnin içindeki TÜM ``{"name": ..., "arguments": {...}}`` nesnelerini bul.

    Yerel küçük modeller araç çağrısını ``tool_calls`` alanı yerine düz metne
    basar; çoğunlukla da birden fazla çağrıyı arka arkaya (genellikle markdown
    çitinde) dizer. Burada dengeli süslü-parantez taramasıyla tüm üst-düzey
    JSON nesneleri çıkarılır:
      * bilinen bir araç adı  -> tool_call formatına çevrilir,
      * ``{"message"/"text"/...}`` -> düz yanıt metni sayılır.
    """
    if not text:
        return [], None
    allowed = set(allowed_names or [])

    calls = []
    final_text = None
    s = text
    n = len(s)
    i = 0
    while i < n:
        pos = s.find("{", i)
        if pos == -1:
            break
        try:
            obj, end = _JSON_DECODER.raw_decode(s, pos)
        except ValueError:
            i = pos + 1
            continue
        if isinstance(obj, dict):
            p_name = obj.get("name")
            p_args = obj.get("arguments", {})
            if isinstance(p_args, str):
                try:
                    p_args = json.loads(p_args)
                except Exception:
                    p_args = {}
            if isinstance(p_name, str) and p_name in allowed:
                calls.append({
                    "id": f"call_{int(time.time() * 1000)}_{len(calls)}",
                    "type": "function",
                    "function": {
                        "name": p_name,
                        "arguments": json.dumps(
                            p_args if isinstance(p_args, dict) else {},
                            ensure_ascii=False,
                        ),
                    },
                })
            elif isinstance(p_args, dict):
                for key in ("message", "text", "response", "content", "answer"):
                    if isinstance(p_args.get(key), str) and p_args[key].strip():
                        if final_text is None:
                            final_text = p_args[key].strip()
                        break
        i = end if end > i else i + 1
    return calls, final_text


# ============================================================
# PROJE ŞABLONLARI (LLM yanıt veremezse çalışan hazır proje)
# ============================================================

# Uygulamanın kendi kökü (backend/.. , ../) — edit akışı buraya DOKUNMAZ.
_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_BUILD_TEMPLATE_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lezzet Durağı | Yemek Sitesi</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
<header class="nav">
  <div class="nav-inner">
    <a class="logo" href="#hero">🍽️ Lezzet Durağı</a>
    <nav class="nav-links">
      <a href="#menu">Menü</a>
      <a href="#hakkimizda">Hakkımızda</a>
      <a href="#iletisim">İletişim</a>
    </nav>
    <button class="nav-toggle" id="navToggle">☰</button>
  </div>
</header>

<section class="hero" id="hero">
  <div class="hero-content">
    <h1>Günlük taze mutfak — Türk mutfağının klasikleri</h1>
    <p>Evinizdeki kadar sıcak, restoranınız kadar keyifli.</p>
    <a class="btn primary" href="#menu">Menüyü Gör</a>
    <a class="btn ghost" href="#iletisim">Sipariş Ver</a>
  </div>
</section>

<section id="menu" class="section">
  <h2>Bugünün Menüsü</h2>
  <div class="menu-grid" id="menuGrid"></div>
</section>

<section id="hakkimizda" class="section alt">
  <h2>Hakkımızda</h2>
  <p>2009'dan beri her sabah pazarından alınan malzemelerle klasik Türk
  yemeklerini hazırlıyoruz. Fırında ramazan pide, taş fırında lahmacun ve
  ev yapımı keşkek sarsılır mı? Bize misafir olun.</p>
</section>

<section id="iletisim" class="section">
  <h2>İletişim</h2>
  <form id="orderForm" class="order-form">
    <input type="text" name="ad" placeholder="Adınız" required>
    <input type="tel" name="telefon" placeholder="Telefon" required>
    <textarea name="not" rows="3" placeholder="Siparişiniz"></textarea>
    <button class="btn primary" type="submit">Gönder</button>
    <p class="form-note" id="formNote"></p>
  </form>
</section>

<footer class="footer">
  <p>© <span id="year"></span> Lezzet Durağı · Tüm hakları saklıdır.</p>
</footer>
<script src="script.js"></script>
</body>
</html>
"""

_BUILD_TEMPLATE_CSS = """/* Lezzet Durağı — stiller */
:root {
  --bg: #fffaf5;
  --ink: #2c2320;
  --muted: #7a6a60;
  --brand: #e2542f;
  --brand-2: #f7a12c;
  --card: #ffffff;
  --border: #efe2d7;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
  background: var(--bg); color: var(--ink); line-height: 1.6;
}
h2 { text-align: center; font-size: 1.9rem; margin-bottom: 1.4rem; }
.section { max-width: 1100px; margin: 0 auto; padding: 3.4rem 1.2rem; }
.section.alt { background: #fdeee3; border-radius: 18px; }

.nav { position: sticky; top: 0; background: var(--card); z-index: 10;
  border-bottom: 1px solid var(--border); }
.nav-inner { max-width: 1100px; margin: 0 auto; display: flex;
  align-items: center; justify-content: space-between; padding: .8rem 1.2rem; }
.logo { font-weight: 700; color: var(--brand); text-decoration: none; font-size: 1.15rem; }
.nav-links a { margin-left: 1rem; color: var(--ink); text-decoration: none; }
.nav-links a:hover { color: var(--brand); }
.nav-toggle { display: none; font-size: 1.1rem; background: none; border: 1px solid var(--border);
  border-radius: 8px; padding: .25rem .6rem; cursor: pointer; }

.hero {
  background: linear-gradient(120deg, #ff6b3d, #f7a12c 75%);
  color: #fff; text-align: center; padding: 4.5rem 1.2rem;
}
.hero h1 { font-size: clamp(1.6rem, 4vw, 2.6rem); max-width: 760px; margin: 0 auto 1rem; }
.hero p { font-size: 1.1rem; opacity: .95; margin-bottom: 1.4rem; }
.btn { display: inline-block; padding: .7rem 1.4rem; border-radius: 999px;
  text-decoration: none; font-weight: 600; margin: .25rem; transition: .2s; }
.btn.primary { background: #fff; color: var(--brand); }
.btn.primary:hover { transform: translateY(-2px); }
.btn.ghost { border: 1.5px solid #fff; color: #fff; }

.menu-grid { display: grid; gap: 1.1rem;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
.dish {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 1.1rem 1.2rem;
  box-shadow: 0 6px 18px rgba(0,0,0,.05);
}
.dish h3 { color: var(--brand); margin-bottom: .35rem; font-size: 1.05rem; }
.dish p { color: var(--muted); font-size: .95rem; }
.dish .price { display: inline-block; margin-top: .6rem; font-weight: 700;
  color: var(--ink); background: var(--bg); border-radius: 8px;
  padding: .15rem .55rem; border: 1px solid var(--border); }

.order-form { max-width: 560px; margin: 0 auto; display: grid; gap: .7rem; }
.order-form input, .order-form textarea {
  padding: .7rem .9rem; border: 1px solid var(--border);
  border-radius: 10px; font: inherit; background: var(--card);
}
.form-note { color: var(--muted); font-size: .9rem; }

.footer { text-align: center; color: var(--muted); padding: 1.6rem 1rem;
  border-top: 1px solid var(--border); }

@media (max-width: 720px) {
  .nav-links {
    display: none; position: absolute; right: 1.2rem; top: 3.4rem;
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: .8rem 1rem; flex-direction: column;
  }
  .nav-links.open { display: flex; }
  .nav-toggle { display: block; }
}
"""

_BUILD_TEMPLATE_JS = """/* Lezzet Durağı — davranışlar */
const MENU = [
  { ad: "Ev Manti", aciklama: "El açması mantı, yoğurt ve kızarmış nane.", fiyat: "₺120" },
  { ad: "Iskender Kebap", aciklama: "Döner, tereyağı ve domates soslu.", fiyat: "₺160" },
  { ad: "Içli Köfte", aciklama: "Bulgur ve kıyma ile klasik içli köfte.", fiyat: "₺90" },
  { ad: "Ramazan Pide", aciklama: "Taş fırında, sıcak servis.", fiyat: "₺45" },
  { ad: "Lahmacun", aciklama: "İnce hamur, bol soğan ve limon.", fiyat: "₺38" },
  { ad: "Baklava", aciklama: "Fistıklı ev yapımı baklava.", fiyat: "₺80" },
  { ad: "Kuru Fasulye", aciklama: "Yanında pilav ve turşu.", fiyat: "₺70" },
  { ad: "Künefe", aciklama: "Yaban fıstığı ile sıcak künefe.", fiyat: "₺95" },
];

function menuList() {
  const grid = document.getElementById("menuGrid");
  if (!grid) return;
  grid.innerHTML = MENU.map((d) => {
    return `<article class="dish">
      <h3>${d.ad}</h3>
      <p>${d.aciklama}</p>
      <span class="price">${d.fiyat}</span>
    </article>`;
  }).join("");
}

function navToggle() {
  const btn = document.getElementById("navToggle");
  const links = document.querySelector(".nav-links");
  if (!btn || !links) return;
  btn.addEventListener("click", () => links.classList.toggle("open"));
}

function orderForm() {
  const form = document.getElementById("orderForm");
  const note = document.getElementById("formNote");
  if (!form) return;
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const data = new FormData(form);
    note.textContent = `Teşekkürler ${data.get("ad") || "Misafir"}! Sipariş notun alınmıştır.`;
    form.reset();
  });
}

const yearEl = document.getElementById("year");
if (yearEl) yearEl.textContent = new Date().getFullYear();

menuList();
navToggle();
orderForm();
"""


# ------------------------------------------------------------------
# ALAN ŞABLONU 1: GELİŞMİŞ YEMEK SİTESİ (arama, filtre, sepet, karanlık mod)
# ------------------------------------------------------------------

_FOOD_TEMPLATE_HTML = r"""<!DOCTYPE html>
<html lang="tr" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lezzet Durağı — Gelişmiş Yemek Sitesi</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
<header class="topbar">
  <div class="brand">🍽️ Lezzet Durağı</div>
  <nav id="nav" class="nav">
    <a href="#hero">Ana Sayfa</a>
    <a href="#menu">Menü</a>
    <a href="#oneriler">Öne Çıkanlar</a>
    <a href="#iletisim">İletişim</a>
  </nav>
  <div class="tools">
    <button id="themeBtn" class="icon-btn" title="Karanlık/Aydınlık mod">🌙</button>
    <button id="cartBtn" class="icon-btn" title="Sepet">🛒<span id="cartBadge" class="badge">0</span></button>
    <button id="navBtn" class="icon-btn" title="Menü (mobil)">☰</button>
  </div>
</header>

<section id="hero" class="hero">
  <h1>Lezzet bir <span class="mark">durak</span>, biz tam göbeğindeyiz</h1>
  <p>Taze malzeme, usta elinde pişen gerçek lezzetler. 30 dakikada kapında.</p>
  <div class="search">
    <input id="q" type="search" placeholder="Ada göre ara: adana kebap, baklava...">
    <button id="qBtn" class="btn">Ara</button>
  </div>
  <p><a class="btn ghost-light" href="#menu">Menüyü Göster</a></p>
</section>

<section class="chips" id="chips"></section>

<section id="menu" class="block">
  <h2>Menü</h2>
  <div id="grid" class="grid"></div>
  <p id="empty" class="empty" hidden>Sonuç bulunamadı 🤷</p>
</section>

<section id="oneriler" class="block">
  <h2>Öne Çıkanlar</h2>
  <div class="grid featured">
    <article class="card feature">
      <div class="thumb">🍢</div>
      <h3>Şef Tabağı</h3>
      <p>Günün en çok tercih edilen üçlüsü tek tabakta.</p>
      <span class="price">₺185</span>
    </article>
    <article class="card feature">
      <div class="thumb">🥗</div>
      <h3>Fit Lezzet</h3>
      <p>Düşük kalorili, bol salata, yanında sade yoğurt.</p>
      <span class="price">₺120</span>
    </article>
    <article class="card feature">
      <div class="thumb">🍕</div>
      <h3>Taştekin Pizza</h3>
      <p>Taş fırında, kenarları çıtır çekilmiş. Bol mozzarella.</p>
      <span class="price">₺140</span>
    </article>
  </div>
</section>

<section id="yorumlar" class="block">
  <h2>Müşteri Yorumları</h2>
  <div class="quotes">
    <blockquote>“Adana sıcaklığı tam iştah açıcı. Servis hızlı!” <cite>— Ayşe K.</cite></blockquote>
    <blockquote>“Sabah kahvaltı için mükemmel. Poğaçalar sıcak sıcak gelir.” <cite>— Mehmet T.</cite></blockquote>
  </div>
</section>

<section id="iletisim" class="block contact">
  <h2>İletişim</h2>
  <div class="contact-wrap">
    <form id="contactForm" novalidate>
      <label>Adınız <input id="cName" required></label>
      <label>Telefon <input id="cPhone" type="tel" required></label>
      <label>Mesaj <textarea id="cMsg" rows="4" required></textarea></label>
      <button class="btn" type="submit">Gönder</button>
      <p id="formMsg" class="form-msg"></p>
    </form>
    <div class="hours">
      <h3>Çalışma Saatleri</h3>
      <ul>
        <li><b>Hafta içi:</b> 08:00 - 22:00</li>
        <li><b>Hafta sonu:</b> 09:00 - 23:00</li>
        <li><b>Sipariş:</b> 📞 (0212) 555 00 01</li>
      </ul>
    </div>
  </div>
</section>

<footer class="footer">
  © <span id="year"></span> Lezzet Durağı · Sosyal: <a href="#">Instagram</a> · <a href="#">X</a>
</footer>

<aside id="drawer" class="drawer" aria-hidden="true">
  <h3>🛒 Sepetim</h3>
  <div id="cartList" class="cart-list"></div>
  <div class="cart-total">Toplam: <b id="cartTotal">₺0</b></div>
  <button id="orderBtn" class="btn wide">Siparişi Ver</button>
  <button id="closeDrawer" class="btn ghost wide">Kapat</button>
</aside>

<div id="toast" class="toast" role="status"></div>
<button id="topBtn" class="top-btn" title="Yukarı">↑</button>
<script src="script.js"></script>
</body>
</html>
"""

_FOOD_TEMPLATE_CSS = r"""/* Lezzet Durağı — gelişmiş tema */
:root{
  --bg:#fff8f2; --panel:#fff; --ink:#2b2118; --muted:#7a6a5c;
  --brand:#e2542f; --brand-2:#f7a12c; --ok:#2e7d32; --danger:#c62828;
  --radius:14px; --shadow:0 8px 24px rgba(43,33,24,.08);
}
[data-theme="dark"]{
  --bg:#17130f; --panel:#221c16; --ink:#f5ece2; --muted:#b9a893;
  --shadow:0 10px 28px rgba(0,0,0,.4);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font-family:system-ui,'Segoe UI',Roboto,Arial;background:var(--bg);color:var(--ink);transition:background .3s,color .3s}
img{max-width:100%}
.topbar{display:flex;align-items:center;gap:1rem;padding:.7rem 1.2rem;background:var(--panel);position:sticky;top:0;z-index:50;box-shadow:var(--shadow)}
.brand{font-weight:800;font-size:1.1rem}
.nav{display:flex;gap:1rem;margin-left:auto}
.nav a{color:var(--ink);text-decoration:none;font-weight:600}
.nav a:hover{color:var(--brand)}
.tools{display:flex;gap:.4rem;margin-left:auto}
.nav + .tools{margin-left:1rem}
.icon-btn{background:transparent;border:1px solid transparent;font-size:1.2rem;cursor:pointer;position:relative;border-radius:10px;padding:.35rem .5rem}
.icon-btn:hover{background:rgba(226,84,47,.12)}
.badge{position:absolute;top:-4px;right:-4px;background:var(--brand);color:#fff;font-size:.65rem;padding:1px 5px;border-radius:999px}
.hero{padding:4.5rem 1.2rem;text-align:center;background:linear-gradient(135deg,var(--brand),var(--brand-2));color:#fff}
.hero h1{margin:.2rem 0;font-size:clamp(1.6rem,4vw,2.6rem)}
.hero .mark{background:rgba(255,255,255,.22);padding:0 .3rem;border-radius:8px}
.search{display:flex;gap:.5rem;max-width:430px;margin:1.2rem auto 0}
.search input{flex:1;padding:.8rem 1rem;border:0;border-radius:12px;font-size:1rem}
.btn{background:var(--brand);color:#fff;border:0;padding:.7rem 1.1rem;border-radius:12px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}
.btn:hover{filter:brightness(1.07)}
.btn.ghost{background:transparent;border:1px solid var(--muted);color:inherit}
.btn.wide{width:100%;margin-top:.5rem}
.chips{display:flex;flex-wrap:wrap;gap:.5rem;justify-content:center;padding:.8rem 1.2rem}
.chip{border:1px solid var(--muted);background:transparent;color:var(--ink);border-radius:999px;padding:.4rem .9rem;cursor:pointer;font-weight:600}
.chip.active{background:var(--brand);border-color:var(--brand);color:#fff}
.block{padding:2.2rem 1.2rem;max-width:1100px;margin:0 auto}
.block h2{text-align:center;margin-bottom:1.2rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:1rem}
.card{background:var(--panel);border-radius:var(--radius);box-shadow:var(--shadow);padding:1rem;display:flex;flex-direction:column;gap:.4rem;transition:transform .15s}
.card:hover{transform:translateY(-3px)}
.thumb{font-size:2rem;text-align:center;background:rgba(247,161,44,.14);border-radius:10px;padding:.8rem}
.price{font-weight:800;color:var(--brand)}
.feature .price{font-size:1.05rem}
.empty{text-align:center;color:var(--muted)}
.quotes{display:grid;gap:1rem;max-width:760px;margin:0 auto}
.quotes blockquote{background:var(--panel);border-left:4px solid var(--brand-2);margin:0;padding:1rem 1.2rem;border-radius:10px;box-shadow:var(--shadow)}
.contact-wrap{display:grid;gap:1.2rem;grid-template-columns:1fr;max-width:820px;margin:0 auto}
@media(min-width:820px){.contact-wrap{grid-template-columns:1.2fr .8fr}}
form{display:grid;gap:.7rem;background:var(--panel);padding:1.2rem;border-radius:var(--radius);box-shadow:var(--shadow)}
label{display:grid;gap:.3rem;font-weight:600;font-size:.9rem}
input,textarea{padding:.7rem .9rem;border:1px solid rgba(0,0,0,.18);border-radius:10px;font:inherit;background:transparent;color:inherit}
input:focus,textarea:focus{outline:2px solid var(--brand-2)}
.hours{background:var(--panel);padding:1.2rem;border-radius:var(--radius);box-shadow:var(--shadow)}
.hours ul{list-style:none;padding:0;margin:.6rem 0 0}
.hours li{padding:.3rem 0;color:var(--muted)}
.footer{border-top:1px solid rgba(0,0,0,.1);padding:1.2rem;text-align:center;color:var(--muted)}
.drawer{position:fixed;top:0;right:-370px;width:340px;height:100vh;background:var(--panel);box-shadow:-12px 0 30px rgba(0,0,0,.18);transition:right .25s;padding:1.2rem;z-index:80;overflow:auto}
.drawer.open{right:0}
.cart-list{display:grid;gap:.6rem;margin:.8rem 0}
.cart-row{display:flex;align-items:center;gap:.5rem;background:var(--bg);border-radius:10px;padding:.5rem .7rem}
.cart-row b{flex:1}
.cart-row .qty{display:flex;gap:.3rem;align-items:center}
.cart-row button{border:0;background:var(--brand-2);color:#3a2c1e;font-weight:800;border-radius:8px;width:26px;cursor:pointer}
.cart-total{text-align:right;margin:.6rem 0}
.toast{position:fixed;left:50%;bottom:1.4rem;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:.7rem 1.2rem;border-radius:999px;opacity:0;pointer-events:none;transition:opacity .25s;z-index:99}
.toast.show{opacity:1}
.top-btn{position:fixed;right:1rem;bottom:1rem;width:42px;height:42px;border-radius:50%;border:0;background:var(--brand);color:#fff;font-size:1.2rem;cursor:pointer;opacity:0;pointer-events:none;transition:opacity .2s}
.top-btn.show{opacity:1}
@media(max-width:720px){
  .nav{display:none;position:fixed;inset:56px 0 auto;background:var(--panel);flex-direction:column;padding:1rem;box-shadow:var(--shadow)}
  .nav.open{display:flex}
}
"""

_FOOD_TEMPLATE_JS = r"""/* Lezzet Durağı — gelişmiş davranışlar */
const MENU = [
  { id:1, ad:"Adana Kebap", kategori:"Kebaplar", fiyat:150, emoji:"🍢" },
  { id:2, ad:"Kuzu Şiş", kategori:"Kebaplar", fiyat:185, emoji:"🥩" },
  { id:3, ad:"Margherita", kategori:"Pizzalar", fiyat:110, emoji:"🍕" },
  { id:4, ad:"Karışık Pizza", kategori:"Pizzalar", fiyat:140, emoji:"🍕" },
  { id:5, ad:"Lazanya", kategori:"Ana Yemek", fiyat:130, emoji:"🍝" },
  { id:6, ad:"Çorba", kategori:"İçecekler", fiyat:35, emoji:"🍲" },
  { id:7, ad:"Baklava", kategori:"Tatlılar", fiyat:65, emoji:"🍰" },
  { id:8, ad:"Sütlaç", kategori:"Tatlılar", fiyat:45, emoji:"🍮" },
  { id:9, ad:"Ayran", kategori:"İçecekler", fiyat:25, emoji:"🥛" },
  { id:10, ad:"Limonata", kategori:"İçecekler", fiyat:35, emoji:"🍋" },
];

const CATEGORIES = ["Tümü", ...new Set(MENU.map(m => m.kategori))];
let aktifKategori = "Tümü";
let cart = {};

const gridEl = document.getElementById("grid");
const chipsEl = document.getElementById("chips");

function ilkSiparis() {
  try { cart = JSON.parse(localStorage.getItem("ld_cart") || "{}"); }
  catch (e) { cart = {}; }
}

function renderChips() {
  chipsEl.innerHTML = "";
  CATEGORIES.forEach(k => {
    const b = document.createElement("button");
    b.className = "chip" + (k === aktifKategori ? " active" : "");
    b.textContent = k;
    b.onclick = () => { aktifKategori = k; render(); };
    chipsEl.appendChild(b);
  });
}

function render(q) {
  const term = (q || "").toLowerCase().trim();
  const liste = MENU.filter(m =>
    (aktifKategori === "Tümü" || m.kategori === aktifKategori) &&
    (!term || m.ad.toLowerCase().includes(term))
  );
  gridEl.innerHTML = "";
  liste.forEach(m => {
    const card = document.createElement("article");
    card.className = "card";
    const icerik =
      '<div class="thumb">' + m.emoji + '</div>' +
      '<h3>' + m.ad + '</h3>' +
      '<span class="price">₺' + m.fiyat + '</span>' +
      '<button class="btn ekle">Sepete Ekle</button>';
    card.innerHTML = icerik;
    card.querySelector(".ekle").onclick = () => sep(m.id);
    gridEl.appendChild(card);
  });
  document.getElementById("empty").hidden = liste.length > 0;
}

function sep(id) {
  cart[id] = (cart[id] || 0) + 1;
  cartKaydet();
  toast(MENU.find(m => m.id === id).ad + " sepete eklendi ✅");
}

function cartKaydet() {
  localStorage.setItem("ld_cart", JSON.stringify(cart));
  renderCart();
}

function renderCart() {
  const entries = Object.entries(cart);
  const list = document.getElementById("cartList");
  let toplam = 0;
  list.innerHTML = "";
  entries.forEach(([id, n]) => {
    const m = MENU.find(x => x.id === Number(id));
    if (!m) return;
    toplam += m.fiyat * n;
    const row = document.createElement("div");
    row.className = "cart-row";
    const html = '<b>' + m.emoji + ' ' + m.ad + '</b>' +
      '<span class="qty"><button data-a="-">−</button><span>' + n + '</span>' +
      '<button data-a="+">+</button></span>' +
      '<span>₺' + (m.fiyat * n) + '</span>';
    row.innerHTML = html;
    row.querySelectorAll("button").forEach(btn => {
      btn.onclick = () => {
        const a = btn.dataset.a;
        cart[id] = a === "+" ? cart[id] + 1 : cart[id] - 1;
        if (cart[id] <= 0) delete cart[id];
        cartKaydet();
      };
    });
    list.appendChild(row);
  });
  if (!entries.length) list.innerHTML = BOS;
  document.getElementById("cartTotal").textContent = "₺" + toplam;
  const n = entries.reduce((s, [k, v]) => s + v, 0);
  document.getElementById("cartBadge").textContent = n;
}

const toastEl = document.getElementById("toast");
function toast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => toastEl.classList.remove("show"), 2200);
}

// Sepet boş metni
const BOS = '<p class="empty">Sepet boş · menüden bir şeyler ekle 🍽️</p>';

// Tema
const themeBtn = document.getElementById("themeBtn");
themeBtn.onclick = () => {
  const root = document.documentElement;
  const dark = root.dataset.theme === "dark";
  root.dataset.theme = dark ? "light" : "dark";
  themeBtn.textContent = dark ? "🌙" : "☀️";
  localStorage.setItem("ld_theme", root.dataset.theme);
};
const kayitTema = localStorage.getItem("ld_theme");
if (kayitTema) {
  document.documentElement.dataset.theme = kayitTema;
  themeBtn.textContent = kayitTema === "dark" ? "☀️" : "🌙";
}

// Sepet / menü butonları
const drawer = document.getElementById("drawer");
document.getElementById("cartBtn").onclick = () => drawer.classList.add("open");
document.getElementById("closeDrawer").onclick = () => drawer.classList.remove("open");
document.getElementById("orderBtn").onclick = () => {
  if (!Object.keys(cart).length) return toast("Sepet boş 🤔");
  toast("Sipariş alındı! 30 dakikada kapında 🚀");
  cart = {}; cartKaydet(); drawer.classList.remove("open");
};

// Mobil nav
document.getElementById("navBtn").onclick = () =>
  document.getElementById("nav").classList.toggle("open");

// Arama
const qEl = document.getElementById("q");
qEl.addEventListener("input", () => render(qEl.value));
document.getElementById("qBtn").onclick = () => render(qEl.value);

// İletişim doğrulama
const form = document.getElementById("contactForm");
form.addEventListener("submit", e => {
  e.preventDefault();
  const msg = document.getElementById("formMsg");
  if (!form.checkValidity()) {
    msg.textContent = "Lütfen tüm alanları doldurun.";
    msg.style.color = "var(--danger)";
    return;
  }
  msg.textContent = "Mesajınız alındı, teşekkürler!";
  msg.style.color = "var(--ok)";
  form.reset();
});

// Scroll efektleri
const topBtn = document.getElementById("topBtn");
window.addEventListener("scroll", () => {
  topBtn.classList.toggle("show", window.scrollY > 400);
});
topBtn.onclick = () => window.scrollTo({ top: 0 });

document.getElementById("year").textContent = new Date().getFullYear();

ilkSiparis();
renderChips();
render();
renderCart();
"""


# ------------------------------------------------------------------
# ALAN ŞABLONU 2: NAMAZ VAKİTLERİ — MOBİL UYGULAMA (PWA hissi)
# ------------------------------------------------------------------

_PRAYER_TEMPLATE_HTML = r"""<!DOCTYPE html>
<html lang="tr" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Namaz Vakitleri</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
<div class="phone">
  <header class="h">
    <div>
      <h1>Namaz Vakitleri</h1>
      <p id="tarih">—</p>
    </div>
    <select id="city" aria-label="Şehir">
      <option>İstanbul</option><option>Ankara</option><option>İzmir</option>
      <option>Bursa</option><option>Adana</option><option>Konya</option>
      <option>Antalya</option><option>Gaziantep</option>
    </select>
  </header>

  <section class="next">
    <p class="lbl">Sıradaki vakit</p>
    <h2 id="nextName">—</h2>
    <p id="nextTime" class="big">--:--</p>
    <p id="kalan" class="kalan">kalan —:—:—</p>
    <div class="bar"><div id="prog"></div></div>
  </section>

  <ul id="rows" class="rows"></ul>

  <section class="actions">
    <button id="notif" class="btn">🔔 Hatırlatıcıyı Aç</button>
    <button id="theme" class="btn ghost">🌗 Tema</button>
  </section>

  <p class="note">Şehir değerleri istasyon örnek değerlerden hazırlanmıştır
  (demo). Tutarlı takip için diyanetin resmi uygulamasını referans alın.</p>
</div>
<script src="script.js"></script>
</body>
</html>
"""

_PRAYER_TEMPLATE_CSS = r"""/* Namaz Vakitleri — mobil tema */
:root{--bg:#0e2a25;--panel:#123a33;--ink:#eafff8;--muted:#9fd4c8;--brand:#34d399;--brand2:#0f766e}
[data-theme="light"]{--bg:#f0fdf9;--panel:#ffffff;--ink:#123a33;--muted:#52796f;--brand:#0f766e;--brand2:#14b8a6}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,Segoe UI,Roboto,Arial;background:linear-gradient(160deg,var(--bg),#1a0d24 340%);color:var(--ink);min-height:100vh;display:flex;justify-content:center;transition:background .3s}
.phone{width:100%;max-width:430px;padding:1.1rem 1rem 2.4rem}
.h{display:flex;justify-content:space-between;align-items:flex-start;gap:.6rem}
h1{font-size:1.35rem;margin:.1rem 0}
.h p{margin:0;color:var(--muted);font-size:.85rem}
select{background:var(--panel);color:var(--ink);border:1px solid var(--brand2);padding:.45rem .7rem;border-radius:12px;font-weight:600}
.next{background:linear-gradient(135deg,var(--brand2),var(--brand));color:#023b34;border-radius:20px;padding:1.1rem;text-align:center;margin:1rem 0;box-shadow:0 12px 28px rgba(15,118,110,.35)}
.next .lbl{opacity:.8;margin:0;font-weight:600;letter-spacing:.4px}
.next h2{margin:.2rem 0;font-size:1.7rem;color:#fff}
.next .big{font-size:2.4rem;font-weight:800;margin:.1rem 0;color:#fff}
.kalan{font-weight:700;margin:0.2rem 0 .6rem}
.bar{height:8px;background:rgba(255,255,255,.3);border-radius:999px;overflow:hidden}
.bar div{height:100%;width:0;background:#fff;transition:width .4s}
.rows{list-style:none;margin:0;padding:0}
.rows li{display:flex;justify-content:space-between;align-items:center;background:var(--panel);padding:.85rem 1rem;border-radius:14px;margin-bottom:.55rem;font-weight:600}
.rows li span:last-child{font-variant-numeric:tabular-nums;color:var(--muted)}
.rows li.soon{border:2px solid var(--brand);transform:scale(1.02)}
.rows li.done{opacity:.5;text-decoration:line-through}
.actions{display:flex;gap:.6rem;margin-top:1rem}
.btn{flex:1;background:var(--brand);color:#05231f;border:0;padding:.75rem;border-radius:14px;font-weight:800;cursor:pointer}
.btn.ghost{background:transparent;border:1px solid var(--brand);color:var(--ink)}
.note{color:var(--muted);font-size:.78rem;line-height:1.5;margin-top:1.2rem}
"""

_PRAYER_TEMPLATE_JS = r"""/* Namaz Vakitleri — mantık */
const VAKITLER = ["İmsak", "Güneş", "Öğle", "İkindi", "Akşam", "Yatsı"];
const TABELA = {
  "İstanbul": ["05:23", "06:28", "12:08", "14:51", "17:02", "18:32"],
  "Ankara": ["05:13", "06:22", "12:02", "14:46", "16:58", "18:30"],
  "İzmir": ["05:38", "06:44", "12:18", "14:57", "17:04", "18:32"],
  "Bursa": ["05:31", "06:36", "12:14", "14:57", "17:10", "18:40"],
  "Adana": ["04:58", "06:16", "11:56", "14:37", "16:52", "18:16"],
  "Konya": ["05:14", "06:26", "12:04", "14:44", "16:58", "18:22"],
  "Antalya": ["05:32", "06:40", "12:06", "14:46", "16:56", "18:20"],
  "Gaziantep": ["04:44", "05:58", "11:42", "14:22", "16:32", "17:52"],
};

let city = localStorage.getItem("nv_city") || "İstanbul";
const cityEl = document.getElementById("city");
cityEl.value = city;
cityEl.onchange = () => { city = cityEl.value; localStorage.setItem("nv_city", city); render(); };

const rowsEl = document.getElementById("rows");
const TR = ["Pazar", "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi"];

function toMin(s) {
  const [h, mi] = s.split(":").map(Number);
  return h * 60 + mi;
}

function nowMin() {
  const d = new Date();
  return d.getHours() * 60 + d.getMinutes() + d.getSeconds() / 60;
}

function hicriTarih(d) {
  try {
    return new Intl.DateTimeFormat("tr-TR-u-ca-islamic", {
      day: "numeric", month: "long", year: "numeric",
    }).format(d) + " hicri";
  } catch (e) { return ""; }
}

function render() {
  const saatler = TABELA[city] || TABELA["İstanbul"];
  const d = new Date();
  document.getElementById("tarih").textContent =
    TR[d.getDay()] + ", " + d.getDate() + " " +
    d.toLocaleString("tr-TR", { month: "long" }) + " · " + hicriTarih(d);
  rowsEl.innerHTML = "";
  VAKITLER.forEach((ad, i) => {
    const li = document.createElement("li");
    li.innerHTML = '<span>' + ad + '</span><span>' + saatler[i] + '</span>';
    li.dataset.min = toMin(saatler[i]);
    rowsEl.appendChild(li);
  });
  tik();
}

function tik() {
  const rows = [...rowsEl.children];
  const n = nowMin();
  let idx = rows.findIndex(li => Number(li.dataset.min) > n);
  let endOfDay = false;
  if (idx === -1) { idx = 0; endOfDay = true; }
  rows.forEach((li, i) => {
    li.classList.toggle("done", endOfDay ? false : Number(li.dataset.min) < n);
    li.classList.toggle("soon", i === idx && !endOfDay);
  });
  document.getElementById("nextName").textContent =
    endOfDay ? "İmsak (yarın)" : VAKITLER[idx];
  document.getElementById("nextTime").textContent =
    rows[idx].children[1].textContent;

  let hedef = Number(rows[idx].dataset.min);
  if (endOfDay) hedef += 24 * 60;
  let start;
  if (idx === 0) {
    // İmsak öncesi/gecesi: başlangıç dünkü/bugünkü Yatsı
    start = Number(rows[rows.length - 1].dataset.min);
    if (!endOfDay) start -= 24 * 60;
  } else {
    start = Number(rows[idx - 1].dataset.min);
  }
  const span = Math.max(1, hedef - start);
  const gecen = Math.min(Math.max(0, n - start), span);
  document.getElementById("prog").style.width =
    Math.round(100 * gecen / span) + "%";

  const kalan = Math.max(0, hedef - n);
  const hour = Math.floor(kalan / 60), min = Math.floor(kalan % 60), sec = Math.floor((kalan % 1) * 60);
  document.getElementById("kalan").textContent =
    "kalan " + String(hour).padStart(2, "0") + ":" +
    String(min).padStart(2, "0") + ":" + String(sec).padStart(2, "0");
}

document.getElementById("theme").onclick = () => {
  const root = document.documentElement;
  root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("nv_theme", root.dataset.theme);
};
const kayitTema = localStorage.getItem("nv_theme");
if (kayitTema) document.documentElement.dataset.theme = kayitTema;

const notifBtn = document.getElementById("notif");
notifBtn.onclick = async () => {
  if (!("Notification" in window)) return alert("Tarayıcı bildirim desteklemiyor.");
  const perm = await Notification.requestPermission();
  if (perm === "granted") {
    new Notification("Namaz Vakitleri", { body: "Vakit uyarıları aktif ✅" });
    notifBtn.textContent = "🔔 Hatırlatıcı Açık";
  } else {
    notifBtn.textContent = "🔕 İzin yok";
  }
};

render();
setInterval(tik, 1000);
"""

_PRAYER_TEMPLATE_MANIFEST = r"""{
  "name": "Namaz Vakitleri",
  "short_name": "Vakitler",
  "start_url": "./index.html",
  "display": "standalone",
  "background_color": "#0e2a25",
  "theme_color": "#0f766e",
  "lang": "tr",
  "description": "Namaz vakitlerini gösteren mobil uyumlu uygulama (demo veri)."
}
"""


# ------------------------------------------------------------------
# ALAN ŞABLONU 3: ÖĞRENCİ GİRİŞİ — MASAÜSTÜ UYGULAMASI (Tkinter)
# ------------------------------------------------------------------

_STUDENT_TEMPLATE_PY = r'''# Ogrenci Girisi - masaustu uygulama (Tkinter)
# Calistirma: python main.py   |  penceresiz oz test: python main.py --check
import json
import os
import sys

VERI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "veri.json")
DB = {}


def veri_yukle():
    if not os.path.exists(VERI):
        demo = {
            "kullanicilar": {
                "2026001": {"sifre": "1234", "ad": "Ali Veli", "sinif": "9-A", "rol": "ogrenci"},
                "2026002": {"sifre": "1234", "ad": "Zeynep Ay", "sinif": "10-B", "rol": "ogrenci"},
                "2026003": {"sifre": "1234", "ad": "Admin K.", "sinif": "-", "rol": "yonetici"},
            },
            "dersler": {
                "2026001": [["Matematik", 90], ["Fizik", 78], ["Turkce", 85], ["Biyoloji", 67], ["Kimya", 91], ["Tarih", 80]],
                "2026002": [["Matematik", 88], ["Fizik", 92], ["Turkce", 76], ["Biyoloji", 81], ["Kimya", 95], ["Tarih", 89]],
            },
            "devamsizlik": {"2026001": 3, "2026002": 1, "2026003": 0},
            "duyurular": [
                "Fizik 1. sinav 12 Kasim'da!",
                "Kutuphane yeni kitaplar geldi.",
            ],
        }
        with open(VERI, "w", encoding="utf-8") as f:
            json.dump(demo, f, ensure_ascii=False, indent=2)
    with open(VERI, "r", encoding="utf-8") as f:
        return json.load(f)


def veri_kaydet():
    with open(VERI, "w", encoding="utf-8") as f:
        json.dump(DB, f, ensure_ascii=False, indent=2)


def giris(no, sifre):
    no = (no or "").strip()
    sifre = (sifre or "").strip()
    if not no or not sifre:
        return None, "Numara ve sifre bos olamaz."
    k = DB["kullanicilar"].get(no)
    if not k:
        return None, "Bu numaraya ait kayit yok."
    if k["sifre"] != sifre:
        return None, "Sifre hatali."
    return no, "Hos geldin, " + k["ad"] + "!"


def ortalama(no):
    ders = DB["dersler"].get(no) or []
    if not ders:
        return 0.0
    return round(sum(n for _, n in ders) / len(ders), 2)


def harf_ort(ort):
    if ort >= 85: return "A"
    if ort >= 70: return "B"
    if ort >= 55: return "C"
    return "F"


class PanelUI:
    # Giris sonrasi yeni pencere: notlar + duyurular
    def __init__(self, master, no):
        import tkinter as tk
        self.win = tk.Toplevel(master) if master else tk.Tk()
        self.on_kapat = None
        k = DB["kullanicilar"].get(no, {})
        self.win.title("Panel - " + k.get("ad", "Ogrenci"))
        self.win.geometry("560x460")
        tk.Label(self.win, text="Ogrenci Paneli", font=("Segoe UI", 15, "bold")).grid(row=0, column=1, pady=(12, 2))
        tk.Label(self.win, text=(k.get("ad", "") + "  |  sinif: " + str(k.get("sinif", "-"))),
                 fg="#555").grid(row=1, column=1)
        ort = ortalama(no)
        tk.Label(self.win, text="Ortalama: " + str(ort) + "  (" + harf_ort(ort) + ")",
                 font=("Segoe UI", 12, "bold"), fg="#2563eb").grid(row=2, column=1, pady=2)
        tk.Label(self.win, text="Devamsizlik: " + str(DB["devamsizlik"].get(no, 0)) + " gun",
                 fg="#a16207").grid(row=3, column=1, pady=2)

        tk.Label(self.win, text="Ders Notlari", font=("Segoe UI", 12, "bold")).grid(row=4, column=0, sticky="w", padx=12, pady=(10, 2))
        for i, (d, n) in enumerate(DB["dersler"].get(no, []), start=5):
            tk.Label(self.win, text=d).grid(row=i, column=0, sticky="w", padx=12)
            tk.Label(self.win, text=str(n), fg="#0f766e").grid(row=i, column=0, sticky="e", padx=120)

        tk.Label(self.win, text="Duyurular", font=("Segoe UI", 12, "bold")).grid(row=4, column=2, sticky="w", padx=12, pady=(10, 2))
        kutu = tk.Text(self.win, width=26, height=10, border=0, bg="#f8fafc")
        kutu.insert("1.0", "\n".join("- " + d for d in DB["duyurular"]))
        kutu.configure(state="disabled")
        kutu.grid(row=5, column=2, rowspan=6, padx=12)

        tk.Button(self.win, text="Cikis", width=12,
                  command=lambda: self.kapat()).grid(row=14, column=1, pady=10)

    def kapat(self):
        self.win.destroy()
        if self.on_kapat:
            self.on_kapat()


class GirisiUI:
    # Ana pencere: numara + sifre ile giris
    def __init__(self):
        import tkinter as tk
        self.win = tk.Tk()
        self.win.title("Ogrenci Girisi")
        self.win.geometry("360x380")
        tk.Label(self.win, text="Ogrenci Girisi", font=("Segoe UI", 16, "bold")).pack(pady=(20, 4))
        tk.Label(self.win, text="Numara ve sifre giriniz:").pack(pady=(0, 8))
        self.fNO = tk.Entry(self.win, font=("Segoe UI", 12), width=22)
        self.fNO.insert(0, DB.get("son_no", ""))
        self.fNO.pack(pady=4, ipady=5)
        self.fSifre = tk.Entry(self.win, show="*", font=("Segoe UI", 12), width=22)
        self.fSifre.pack(pady=4, ipady=5)
        tk.Button(self.win, text="Giris Yap", width=18, bg="#2563eb", fg="white",
                  font=("Segoe UI", 12, "bold"), command=self.gir_ana).pack(pady=10)
        tk.Label(self.win, text="Demo ogrenci: 2026001 / 1234", fg="#7a6a5c").pack()
        tk.Label(self.win, text="Demo yonetici: 2026003 / 1234", fg="#7a6a5c").pack()
        self.durum = tk.Label(self.win, text="", fg="#c62828")
        self.durum.pack(pady=6)
        self.win.bind("<Return>", lambda e: self.gir_ana())

    def gir_ana(self):
        no, mesaj = giris(self.fNO.get(), self.fSifre.get())
        if not no:
            self.durum.configure(text=mesaj, fg="#c62828")
            return
        DB["son_no"] = no
        veri_kaydet()
        self.win.withdraw()
        self.panel = PanelUI(self.win, no)
        self.panel.on_kapat = self.pana_kapat
        self.panel.win.protocol("WM_DELETE_WINDOW", self.pana_kapat)

    def pana_kapat(self):
        self.win.destroy()


def oztest():
    global DB
    DB = veri_yukle()
    no, _msg = giris("2026001", "1234")
    bozuk, hata = giris("2026001", "yanlis")
    yok, _ = giris("9999999", "1234")
    ort_b = harf_ort(ortalama("2026002"))
    sonuc = (
        no == "2026001"
        and bozuk is None and hata == "Sifre hatali."
        and yok is None
        and ort_b == "A"
    )
    print("CHECK:", "OK" if sonuc else "FAIL", "| ortalama(2026002):", ortalama("2026002"), ort_b)
    return 0 if sonuc else 1


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(oztest())
    DB = veri_yukle()
    try:
        import tkinter as tk  # noqa: F401
    except ImportError:
        print("Bu uygulama tkinter gerektirir (standart Python kurulumunda vardir).")
        sys.exit(1)
    app = GirisiUI()
    app.win.mainloop()
'''

_STUDENT_TEMPLATE_README = r"""# Öğrenci Girişi — Masaüstü Uygulaması

Gerçek bir masaüstü uygulamasıdır (Python/Tkinter). Kurulum gerektirmez.

## Çalıştırma
```
python main.py
```
## Öz test (pencere açmadan)
```
python main.py --check
```

## Demo hesaplar
- Öğrenci: `2026001` / şifre `1234`
- Diğer öğrenci: `2026002` / `1234`
- Yönetici: `2026003` / `1234`

## Neler var?
- Giriş penceresi: numara/şifre doğrulama, Enter ile giriş, beni hatırla (son numara).
- Panel penceresi: öğrenci adı, ortalama (harf notuyla), devamsızlık, ders notları, duyurular.
- Veriler `veri.json` içinde; uygulama ilk çalışmada örnek veri üretir.

İyi çalışmalar! 🎓
"""

_STUDENT_TEMPLATE_DATA = r"""{
  "kullanicilar": {},
  "dersler": {},
  "devamsizlik": {},
  "duyurular": []
}
"""


def _parse_retry_after(response, default: float = 20.0) -> float:
    """Extract a sane wait time (seconds) from a 429 response.

    Prefers the ``Retry-After`` header; falls back to parsing provider-style
    messages such as "Please try again in 12.5s" or "in 1m30s". Sleeps are
    capped so a bad value can never hang the request for minutes.
    """
    try:
        header = response.headers.get("retry-after") or response.headers.get("Retry-After")
        if header:
            try:
                return max(1.0, min(float(header), 90.0))
            except (TypeError, ValueError):
                pass
    except Exception:
        pass
    try:
        body = response.text or ""
    except Exception:
        body = ""
    m = re.search(r"try again in\s+(\d+)m([\d.]+)s", body, re.IGNORECASE)
    if m:
        return max(1.0, min(int(m.group(1)) * 60 + float(m.group(2)) + 1.0, 120.0))
    m = re.search(r"try again in\s+([\d.]+)\s*s", body, re.IGNORECASE)
    if m:
        return max(1.0, min(float(m.group(1)) + 1.0, 90.0))
    return default


class NexusAIAgent:
    """
    True AI Agent powered by LLM.
    Understands natural language, selects tools, generates responses.
    """
    
    def __init__(self, llm_config: LLMConfig = None):
        """Yalnızca yerel Ollama modelini kullan."""
        import local_llm
        base_url = local_llm.configured_url() or "http://127.0.0.1:11434/v1"
        model = local_llm.model_name() or "qwen2.5:3b"
        provider = "local"
        
        self.llm_config = llm_config or LLMConfig(
            api_key="", base_url=base_url, model=model
        )
        self.provider = provider
        logger.info(f"LLM Provider: {provider} | Model: {model}")
        
        # Initialize Brain for continuous learning
        self.brain = get_brain()
        
        self.memory = ConversationMemory(max_history=30)
        self.learning = LearningMemory()
        # Working directory for file operations (project root)
        working_dir = os.environ.get("NEXUS_WORKING_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.tools = ToolExecutor(working_dir=working_dir)
        self.system_prompt = self._build_system_prompt()
        # Per-chat tool allow-list (set from the active custom agent in chat()).
        # None => kısıt yok (tüm araçlar); [] => hiç araç (fail-closed).
        self._active_tools = None

    # --- İstek-yerel durum (contextvar) ---------------------------------
    # Instance attribute yerine contextvar: eşzamanlı sohbetler izolasyonlu.
    @property
    def _active_tools(self):
        return _ACTIVE_TOOLS.get()

    @_active_tools.setter
    def _active_tools(self, value):
        _ACTIVE_TOOLS.set(value)

    @property
    def _active_model(self):
        return _ACTIVE_MODEL.get()

    @_active_model.setter
    def _active_model(self, value):
        _ACTIVE_MODEL.set(value)

    def _refresh_llm_config(self):
        """Refresh LLM config from model_config.json (Yerel Ollama)."""
        try:
            from model_routes import (
                _load_config, LOCAL_PROVIDER_ID,
                LOCAL_DEFAULT_BASE_URL, LOCAL_DEFAULT_MODEL,
            )
            import local_llm

            config = _load_config()
            active_model = config.get("active_model")
            base_url = (
                local_llm.configured_url()
                or os.getenv(local_llm.ENV_URL)
                or LOCAL_DEFAULT_BASE_URL
            ).rstrip("/")
            model = (
                active_model
                or local_llm.model_name()
                or LOCAL_DEFAULT_MODEL
            )
            self.llm_config.api_key = ""
            self.llm_config.base_url = base_url
            self.llm_config.model = model
            self.provider = LOCAL_PROVIDER_ID
        except Exception as e:
            logger.warning(f"Could not refresh LLM config: {e}")
    
    def _build_system_prompt(self, query: str = "") -> str:
        """Build the agent's system prompt with brain context."""
        brain_context = ""
        if query and hasattr(self, 'brain') and self.brain:
            brain_context = self.brain.get_context_for_llm(query)
            if brain_context and brain_context != "No prior learning context.":
                brain_context = f"\n\nBRAIN CONTEXT (learned from experience):\n{brain_context}\n"
        
        working_dir = getattr(self.tools, 'working_dir', 'current directory')
        
        return f"""You are NEXUS-CORE v6.1, an advanced AI coding agent with file system and command execution capabilities (like OpenCode/Cursor).
{brain_context}
You are working in: {working_dir}

## CORE CAPABILITIES

### 1. CODE ASSISTANT
- Generate production-ready code in any language
- Read, write, edit files in the project
- Search code across the project
- Execute shell commands
- Fix bugs, refactor code, add features

### 2. FILE OPERATIONS
- read_file: Read file contents (with line numbers)
- write_file: Create or overwrite files
- edit_file: Modify files by replacing text
- list_files: Explore project structure
- search_files: Find code/patterns across files

### 3. COMMAND EXECUTION
- execute_command: Run shell commands, scripts, install packages
- Can start servers, run tests, git operations, etc.

### 4. MULTIMODAL GENERATION
- generate_code: Create code from natural language
- generate_visual_prompt: AI art prompts (Midjourney, SD, DALL-E)
- generate_image: Generate ACTUAL IMAGE FILES using free Pollinations.ai (Flux, DALL-E, Midjourney styles). Returns direct image URL.
- generate_video_prompt: Cinematic video prompts (Veo, Sora, Runway)
- generate_real_video: Generate ACTUAL MP4 video files from text (~20s, free)

### 5. KNOWLEDGE & RESEARCH
- web_search: Search the web for current information
- search_learning: Search past interactions for patterns
- answer_question: Answer general knowledge questions

## REASONING FRAMEWORK (Chain of Thought)

Think through problems step-by-step before acting:

1. **UNDERSTAND** - What is the user really asking? What's the goal?
2. **PLAN** - What steps are needed? Which tools in what order?
3. **EXECUTE** - Use tools systematically, one at a time
4. **OBSERVE** - Analyze tool results, adjust if needed
5. **REFLECT** - Review the outcome, verify correctness
6. **RESPOND** - Provide clear, complete answer

## RULES

- Always respond in the SAME LANGUAGE as the user (Turkish if user writes Turkish, English if English)
- Be thorough but concise
- When editing files, show the user what you changed
- After edits, run tests or verify if appropriate
- For file operations, always use relative paths from the working directory
- Show file paths when discussing files
- Use markdown for code blocks
- When running commands, show the output
- If something fails, debug and fix it
- **Think before you act** - Complex tasks need planning
- **COMPLETE MULTI-STEP TASKS**: When the user asks for a multi-step deliverable (create a project, write several files, build a site/app), do ALL the steps with tools BEFORE answering. Do NOT stop after a single tool call, and do NOT merely describe what could be done — actually create/edit every required file, then verify (list files / run the command) and only then report.
- Never leave a task half-finished. If a tool returns an error, diagnose it and retry with a corrected call instead of giving up.
- Write file contents IN FULL — never abbreviate with "..." or placeholders.

## EXAMPLE WORKFLOW

User: "Fix the bug in main.py where login fails"

1. **Understand**: User wants login bug fixed in main.py
2. **Plan**: Read file → Analyze → Edit → Test → Explain
3. **Execute**: 
   - read_file("main.py") - Find the login function
   - Analyze the code
   - edit_file("main.py", old_text="...", new_text="...") - Fix the bug
   - execute_command("python -c 'import main'") - Verify it works
4. **Reflect**: Did the fix work? Any side effects?
5. **Respond**: Explain the fix and verification

## SELF-REFLECTION GUIDELINES

After completing a task, ask yourself:
- Did I fully answer the user's question?
- Are there edge cases I missed?
- Is the solution robust and maintainable?
- Should I suggest improvements or alternatives?

When you need to use tools, call them. Work like a real coding assistant — read code before editing, test after changes."""

    async def chat(self, user_message: str, conversation_id: str = None, history: List[Dict] = None, agent_id: str = None, tools_override: List[str] = None, system_prefix: str = None, current_user = None) -> Dict:
        """
        Main chat interface. Processes user message through LLM with tool use.
        Records experience in brain for continuous learning.

        tools_override : adım-bazlı EN AZ YETKİ için araç allow-list'i ZORLAR
                         (Kodlama Yöneticisi kullanır; yazma adımında salt-okuma
                         araçlarına daraltılabilir).
        system_prefix  : sistem istemine eklenen kısa ön-ek (görev tanımı/rol).
        current_user   : authenticated user for API key access
        """
        import time
        start_time = time.time()
        
        # Store current user for LLM config refresh
        self._current_user = current_user
        
        # Refresh LLM config with user's API keys
        self._refresh_llm_config()
        custom_system_prompt = None
        self._active_tools = None  # reset per chat; set below if a custom agent is used
        self._active_model = None

        # Otomatik ajan seçimi kaldırıldı. Eski istemcilerden 'auto' gelirse
        # yalnızca Ana Yönetici kullanılır; istek bazlı uzman seçimi yapılmaz.
        if agent_id == "auto":
            agent_id = "main-manager"

        if agent_id:
            try:
                from custom_agents import get_agent
                custom_agent = get_agent(agent_id)
                if custom_agent is None:
                    # Silinmiş/eski bir ajan ID'si gelirse tanımsız ajanla tüm
                    # araçlara erişim açılmasın; resmî varsayılana yönlendir.
                    logger.warning(
                        "Ajan bulunamadı (%s); main-manager kullanılacak", agent_id
                    )
                    agent_id = "main-manager"
                    custom_agent = get_agent(agent_id)
                if custom_agent:
                    custom_system_prompt = custom_agent.get("system_prompt")
                    self._active_tools = custom_agent.get("tools") or None
                    if custom_agent.get("model"):
                        self._active_model = custom_agent["model"]
            except Exception as e:
                logger.debug(f"Custom agent load error: {e}")

        # Adım-bazlı araç izni: Kodlama Yöneticisi en az yetki ilkesini böyle uygular.
        if tools_override is not None:
            self._active_tools = list(tools_override)
            if not self._active_tools:
                # Boş liste = hiçbir araç yok (kesinlikle yazma yapamaz).
                self._active_tools = []
        if system_prefix:
            custom_system_prompt = (
                (custom_system_prompt + "\n\n") if custom_system_prompt else ""
            ) + system_prefix
        
        # Get or create conversation
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())[:12]
        
        conv = self.memory.get_or_create(conversation_id)

        # Kimlik soruları model/anahtar durumundan BAĞIMSIZ ve deterministik
        # yanıtlanır. Böylece yerel model kapalı veya OpenRouter anahtarı
        # geçersizken bile kullanıcı "Üzgünüm, yanıt üretemiyorum" hatası
        # yerine doğru bir kendini tanıtma alır.
        if self._is_identity_query(user_message):
            identity_text = self._identity_text()
            self.memory.add_message(conversation_id, Message(role="user", content=user_message))
            self.memory.add_message(conversation_id, Message(role="assistant", content=identity_text))
            return {
                "success": True,
                "response": identity_text,
                "conversation_id": conversation_id,
                "tools_used": [],
                "files_changed": [],
                "iterations": 0,
                "thinking_steps": [
                    {"type": "thinking", "content": "Kimlik ve model bilgisi hazırlanıyor", "icon": "🧠"},
                    {"type": "complete", "content": "Yanıt hazır", "icon": "✨"},
                ],
            }

        # Build message history for LLM with DYNAMIC brain context
        if custom_system_prompt:
            # Build tool guidance strictly for active tools to prevent tool mismatch hallucinations
            available_set = set(self._active_tools) if self._active_tools else {t["function"]["name"] for t in TOOLS}
            tool_doc = {
                "read_file": "- read_file: Dosya oku",
                "write_file": "- write_file: Dosya yaz/oluştur",
                "edit_file": "- edit_file: Dosyada düzenle",
                "list_files": "- list_files: Klasör listele",
                "search_files": "- search_files: Dosyalarda ara",
                "execute_command": "- execute_command: Komut çalıştır",
                "generate_code": "- generate_code: Üretim hazır kod önerisi oluştur (DOSYAYA YAZMAZ; dosya için write_file kullan)",
                "generate_image": "- generate_image: Gerçek görsel dosyası üret (URL döndürür)",
                "generate_visual_prompt": "- generate_visual_prompt: Midjourney/DALL-E/SD için görsel prompt",
                "generate_video_prompt": "- generate_video_prompt: Veo/Sora/Runway için video prompt",
                "generate_real_video": "- generate_real_video: Gerçek MP4 video dosyası oluştur (ücretsiz, ~20sn sürer)",
                "calculate": "- calculate: Güvenli matematiksel ve istatistiksel hesaplama yap",
                "rag_search": "- rag_search: Bilgi tabanındaki belgelerde semantik arama yap",
                "rag_add_document": "- rag_add_document: Bilgi tabanına belge ekle",
                "rag_list_documents": "- rag_list_documents: Bilgi tabanındaki belgeleri listele",
                "rag_delete_document": "- rag_delete_document: Bilgi tabanından belge sil",
                "rag_get_stats": "- rag_get_stats: Bilgi tabanı istatistiklerini getir",
                "web_search": "- web_search: Web'de güncel bilgi ara",
                "search_learning": "- search_learning: Geçmiş deneyimlerde ara",
                "answer_question": "- answer_question: Genel bilgi sorularını cevapla",
            }
            active_guides = [tool_doc[t] for t in available_set if t in tool_doc]
            tools_block = "\n".join(active_guides) if active_guides else "Özel bir araç atanmadı; doğrudan yanıt ver."

            system_prompt = custom_system_prompt + f"""

## KULLANILABİLİR ARAÇLARIN
{tools_block}

## GÖREV TAMAMLAMA PROTOKOLÜ (ÇOK ÖNEMLİ)

Kullanıcı çok adımlı bir görev verdiğinde (örn. "bir site hazırla", "3 dosya oluştur", "proje kur ve çalıştır"):

1. **PLANLA**: Görevi küçük, net adımlara böl. Kaç dosya/değişiklik gerektiğini belirle.
2. **TAMAMEN YÜRÜT**: Görev bitene kadar araçları sırayla çağır. Yalnızca sana atanmış araçları kullan; bu liste dışındaki araçları ÇAĞIRMA. **Tek bir araç çağrısından sonra DURMA.** İstenen TÜM adımları tamamla. Yarım bırakma.
3. **DOĞRULA**: Bitince sonucu kontrol et (dosyaları listele, çıktıyı incele).
4. **HATA OLURSA**: Araç hata verirse pes etme; hatanın nedenini bul, düzelt ve görevi sürdür.
5. **RAPORLA**: Ancak her şey bittikten sonra kullanıcıya ne yaptığını özetleyen net bir metin yanıt ver.

Kurallar:
- Sana atanmamış araçları asla çağırma.
- Görevi asla "yapılabilir" diye tarif edip bırakma — GERÇEKTEN YAP.
- Dosya içeriğini tam yaz; "..." ile kısaltma.
- Türkçe yanıt ver."""
        else:
            system_prompt = self._build_system_prompt(user_message)
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history
        if history:
            messages.extend(history)
        else:
            stored = self.memory.get_history(conversation_id, include_system=False)
            messages.extend(stored[-10:])
        
        messages.append({"role": "user", "content": user_message})
        
        # Persist user message AFTER building the prompt to avoid duplication:
        # get_history() already returns stored messages, so adding it before the
        # prompt build made the current user message appear twice to the LLM.
        self.memory.add_message(conversation_id, Message(role="user", content=user_message))
        
        # Detect intent for brain recording
        intent = self._detect_intent(user_message)
        
        # Call LLM with tool use
        try:
            tools_used = []
            # Gerçekten DEĞİŞEN dosyalar (araç sonucunun `path` alanından).
            # Rapor "0 dosya değişti" yalanı söylemesin: kanıt araç sonucudur.
            files_changed: List[str] = []
            tool_failures = 0
            full_response = ""
            thinking_steps = []  # Track thinking process
            
            # Add initial thinking step
            thinking_steps.append({
                "type": "thinking",
                "content": f"Sorunuz analiz ediliyor: \"{user_message[:100]}\"",
                "icon": "🧠"
            })
            
            max_iterations = 5
            iteration = -1
            llm_failure: Optional[str] = None
            # Site/uygulama/proje inşa + mevcut proje düzenleme istekleri
            # deterministik kanada gider: küçük yerel modeller araç döngüsünde
            # gereksiz onlarca çağrı yapıp dakikaları harcarken dosya bile
            # açmazdı. (Kodlama zinciri uzman adımları etkilenmez.)
            _skip_agent_loop = (
                system_prefix is None
                and (bool(self._is_build_request(user_message))
                     or bool(self._is_edit_request(user_message)))
            )
            for iteration in range(max_iterations):
                if _skip_agent_loop:
                    logger.info("Build/Edit isteği: ajan araç döngüsü atlanıyor")
                    break
                llm_response = await self._call_llm(messages)

                if not llm_response.get("success") or "data" not in llm_response:
                    # _call_llm kendi fallback zincirini zaten çalıştırır.
                    # Aynı hatayı 25 kez tekrarlamak (özellikle yavaş yerel
                    # modelde) kaynak israfıdır; ilk kesin hatada durulur.
                    llm_failure = llm_response.get("error") or "LLM yanıtı alınamadı"
                    logger.warning(
                        "LLM call failed in iteration %s: %s",
                        iteration, llm_failure,
                    )
                    break

                response_data = llm_response["data"] or {}
                choices = response_data.get("choices", [])
                
                if not choices:
                    break
                
                choice = choices[0]
                message = choice.get("message", {})
                tool_calls = message.get("tool_calls", [])
                
                # Yerel modeller bazen tool_calls yerine content içine JSON araç
                # çağrısı basar; çoğu zaman da BİRDEN ÇOK çağrıyı arka arkaya
                # (düz metin/çit içinde) dizer. Tümünü çıkarıp çalıştır.
                if not tool_calls and message.get("content"):
                    _allowed_names = [
                        t.get("function", {}).get("name")
                        for t in (self._tools_payload() or [])
                    ]
                    _found_calls, _found_final = _extract_tool_json_calls(
                        message["content"], _allowed_names
                    )
                    if _found_final and not _found_calls:
                        full_response = _found_final
                    if _found_calls:
                        tool_calls = _found_calls

                # If there's content alongside tool calls, add as thinking
                if message.get("content") and tool_calls:
                    thinking_steps.append({
                        "type": "reasoning",
                        "content": message["content"][:300],
                        "icon": "💭"
                    })
                
                if not tool_calls:
                    if not full_response:
                        full_response = message.get("content", "")
                    break
                
                messages.append(message)
                
                # Derinlemesine savunma: executor'a etkin araç allow-list'ini ver.
                _allowed_tools = self._allowed_tool_names()
                _stop_after_tool = False
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        logger.warning("Skipping malformed tool_call (not a dict)")
                        continue
                    fn = tool_call.get("function") or {}
                    func_name = fn.get("name")
                    call_id = tool_call.get("id")
                    if not func_name or not call_id:
                        logger.warning(f"Skipping malformed tool_call (name={func_name!r}, id={call_id!r})")
                        continue
                    try:
                        raw_args = fn.get("arguments", "{}") or "{}"
                        func_args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args if isinstance(raw_args, dict) else {})
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in tool args: {str(fn.get('arguments', ''))[:100]}")
                        func_args = {}
                    
                    # Add tool thinking step
                    tool_desc = self._get_tool_description(func_name, func_args)
                    thinking_steps.append({
                        "type": "tool",
                        "content": tool_desc,
                        "icon": self._get_tool_icon(func_name),
                        "tool": func_name
                    })
                    
                    tool_result = await self.tools.execute(func_name, func_args, allowed=_allowed_tools)
                    tools_used.append(func_name)

                    # Değişen dosyayı yalnızca araç BAŞARILI olduysa kaydet.
                    if (isinstance(tool_result, dict) and tool_result.get("success")
                            and func_name in ("write_file", "edit_file")):
                        _path = tool_result.get("path") or func_args.get("path")
                        if _path and _path not in files_changed:
                            files_changed.append(_path)
                    
                    # Add tool result summary
                    result_summary = self._summarize_tool_result(func_name, tool_result)
                    if result_summary:
                        thinking_steps.append({
                            "type": "result",
                            "content": result_summary,
                            "icon": "✅"
                        })
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(tool_result, ensure_ascii=False)
                    })

                    # If a tool failed, nudge the model to RECOVER instead of
                    # silently continuing with a broken step (root cause of many
                    # half-finished multi-step tasks).
                    if isinstance(tool_result, dict) and tool_result.get("success") is False:
                        tool_failures += 1
                        err = tool_result.get("error") or tool_result.get("message") or ""
                        messages.append({
                            "role": "user",
                            "content": (
                                f"[SİSTEM NOTU] '{func_name}' aracı hata verdi: {str(err)[:300]}. "
                                "Nedeni gider, gerekirse farklı bir yol dene ve görevi tamamla. "
                                "Kullanıcıya yarım bırakma."
                            )
                        })
                    
                    self.memory.add_message(conversation_id, Message(
                        role="assistant", content=message.get("content", ""), tool_calls=[tool_call]
                    ))
                    self.memory.add_message(conversation_id, Message(
                        role="tool", content=json.dumps(tool_result, ensure_ascii=False), tool_call_id=call_id
                    ))
                    if (func_name in ("generate_code", "write_file", "edit_file")
                            and isinstance(tool_result, dict)
                            and tool_result.get("success")):
                        if func_name == "generate_code":
                            full_response = (
                                "Iste istediginiz kod (" + str(tool_result.get("language", "python")) + " - "
                                + str(tool_result.get("mode", "script")).upper() + " modu):\n\n"
                                + "```" + str(tool_result.get("language", "python")) + "\n"
                                + str(tool_result.get("code", "")) + "\n```\n\n"
                                + "Bu kodu kopyalayip dogrudan kullanabilirsiniz. Degisiklik ister misiniz?"
                            )
                        elif func_name == "write_file":
                            full_response = "Dosya yazildi: " + str(tool_result.get("path"))
                        else:
                            full_response = "Dosya duzenlendi: " + str(tool_result.get("path"))
                        _stop_after_tool = True
                        logger.info("STOP_AFTER_TOOL triggered: %s", func_name)
            
                if _stop_after_tool:
                    logger.info("BREAKING outer loop")
                    break

            # BUILD/EDIT YETKİSİ: kullanıcı sohbette site/uygulama inşa veya
            # mevcut proje düzenleme istedi ve araç döngüsü hiç dosya yazmadıysa
            # deterministik üretici/düzenleyici devreye girer.
            if _skip_agent_loop and not files_changed:
                _bf = None
                try:
                    _bf = await self._smart_build_or_edit(user_message, full_response)
                except Exception as _bf_err:
                    logger.warning("Build/Edit fallback hatası: %s", _bf_err)
                if _bf:
                    files_changed = list(_bf.get("files") or [])
                    full_response = _bf.get("response") or full_response
                    for _n in (_bf.get("notes") or []):
                        thinking_steps.append({
                            "type": "reasoning", "content": _n, "icon": "🩹",
                        })

            # If loop ended without a text response, make one final call WITHOUT
            # tools. Yerel model seçiliyken buluta sessizce geçilmez.
            provider = getattr(self, 'provider', 'openrouter')
            if not full_response and provider not in ("local", "opencode"):
                try:
                    import httpx
                    # Get current config
                    api_key = self.llm_config.api_key
                    base_url = self.llm_config.base_url or "https://openrouter.ai/api/v1"
                    model = self.llm_config.model
                    
                    if api_key and api_key not in ("sk-placeholder", ""):
                        # Trim messages to avoid token limits (same safe window as _call_llm).
                        final_messages = self._safe_window(messages, max_messages=20)
                        final_messages.append({
                            "role": "user",
                            "content": f"Kullanıcının sorusu: {user_message}\n\nYukarıdaki tüm araç sonuçlarını analiz et ve kullanıcının sorusuna kapsamlı bir yanıt ver. Sadece metin yanıt ver, tool kullanma."
                        })
                        
                        payload = {
                            "model": model,
                            "messages": final_messages,
                            "temperature": 0.7,
                            "max_tokens": 4096
                        }
                        headers = {
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json"
                        }
                        if provider == "openrouter":
                            headers["HTTP-Referer"] = "http://localhost:8080"
                            headers["X-Title"] = "NEXUS-CORE"
                        
                        async with httpx.AsyncClient(timeout=90) as client:
                            resp = None
                            for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
                                resp = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
                                if resp.status_code != 429 or attempt >= _RATE_LIMIT_MAX_RETRIES:
                                    break
                                wait = min(_parse_retry_after(resp), _MAX_RATE_LIMIT_WAIT)
                                logger.warning(
                                    f"Final call rate limited (429); waiting {wait:.1f}s "
                                    f"before retry {attempt + 1}/{_RATE_LIMIT_MAX_RETRIES}"
                                )
                                await asyncio.sleep(wait)
                            if resp is not None and resp.status_code == 200:
                                data = resp.json()
                                choices = data.get("choices", [])
                                if choices:
                                    full_response = choices[0].get("message", {}).get("content", "")
                                    logger.info(f"Final response generated: {len(full_response)} chars")
                            else:
                                logger.warning(f"Final call failed: {resp.status_code if resp is not None else '?'}")
                except Exception as fe:
                    logger.warning(f"Final response generation failed: {fe}")
            
            # Sağlayıcı hiç metin üretmediyse bu bir BAŞARIDIR denemez.
            # Kullanıcıya yardımcı metin gösterilir ama `success=False` döner;
            # aksi halde Kodlama Yöneticisi sahte bir "tamamlandı" üretir.
            provider_failed = False
            if not full_response:
                if files_changed:
                    # Yerel/küçük modeller araç çağrısından sonra kapanış metni
                    # üretmeyebilir. Dosya gerçekten yazıldıysa bu bir sağlayıcı
                    # arızası değildir; kanıta dayalı deterministik özet döner.
                    full_response = (
                        "Değişen dosyalar: " + ", ".join(files_changed)
                        + f". {len(tools_used)} araç çalıştırıldı"
                        + (f"; {tool_failures} araç çağrısı hata verdi." if tool_failures else ".")
                    )
                elif tools_used and not tool_failures:
                    full_response = f"{len(tools_used)} araç başarıyla çalıştırıldı."
                else:
                    provider_failed = True
                    if provider == "local":
                        full_response = (
                            "Yerel model (`%s`) şu anda yanıt üretemedi. "
                            "Ollama servisinin (http://127.0.0.1:11434) çalıştığını ve modelin yüklü olduğunu kontrol edin."
                            % (getattr(self.llm_config, "model", "qwen2.5:3b") or "qwen2.5:3b")
                        )
                    elif tools_used:
                        full_response = f"Analiz tamamlandı. {len(tools_used)} araç kullanıldı. Sonuçlar işlendi ancak metin yanıt oluşturulamadı. Lütfen tekrar deneyin."
                    else:
                        full_response = "Üzgünüm, bir yanıt üretemedim. Lütfen tekrar deneyin."
            
            # Add self-reflection step if we have a response
            if full_response and len(full_response) > 50:
                thinking_steps.append({
                    "type": "reflection",
                    "content": "Yanıt gözden geçirildi ve doğrulandı",
                    "icon": "✨"
                })
            
            # Store assistant response
            self.memory.add_message(conversation_id, Message(role="assistant", content=full_response))
            
            # Record in learning memory (legacy)
            self.learning.record(
                query=user_message[:200],
                tools_used=tools_used,
                success=bool(full_response),
                response_summary=full_response[:200]
            )
            
            # === BRAIN: Record experience for continuous learning ===
            latency_ms = int((time.time() - start_time) * 1000)
            self.brain.record_experience(
                user_query=user_message,
                intent_detected=intent,
                tools_used=tools_used,
                success=bool(full_response),
                response_summary=full_response[:300],
                latency_ms=latency_ms,
                tokens_used=0,  # Could be extracted from LLM response
                context={"conversation_id": conversation_id, "iterations": iteration + 1}
            )
            
            # Add final thinking step
            thinking_steps.append({
                "type": "complete",
                "content": "Yanıt hazırlanıyor...",
                "icon": "✨"
            })
            
            return {
                "success": not provider_failed,
                "response": full_response,
                "conversation_id": conversation_id,
                "tools_used": tools_used,
                "files_changed": files_changed,
                "iterations": iteration + 1,
                "thinking_steps": thinking_steps,
                "provider": provider,
                "model": getattr(self.llm_config, "model", None),
                "degraded": bool(llm_failure) or provider_failed,
                "error": (llm_failure or "LLM boş yanıt döndürdü")
                if provider_failed else None,
            }
            
        except Exception as e:
            import traceback
            logger.error(f"Chat error: {e}\n{traceback.format_exc()}")
            
            # Record failed experience
            latency_ms = int((time.time() - start_time) * 1000)
            self.brain.record_experience(
                user_query=user_message,
                intent_detected=intent,
                tools_used=[],
                success=False,
                response_summary="",
                latency_ms=latency_ms,
                error=str(e)
            )
            
            return {"success": False, "error": str(e), "conversation_id": conversation_id}
    
    def _get_tool_description(self, func_name: str, args: dict) -> str:
        """Generate human-readable tool description in Turkish."""
        if func_name == "read_file":
            path = args.get("path", "")
            return f"📖 Dosya okunuyor: {path}"
        elif func_name == "write_file":
            path = args.get("path", "")
            return f"📝 Dosya yazılıyor: {path}"
        elif func_name == "edit_file":
            path = args.get("path", "")
            return f"✏️ Dosya düzenleniyor: {path}"
        elif func_name == "list_files":
            path = args.get("path", ".")
            return f"📁 Klasör listeleniyor: {path}"
        elif func_name == "search_files":
            pattern = args.get("pattern", "")
            return f"🔍 Aranıyor: \"{pattern}\""
        elif func_name == "execute_command":
            cmd = args.get("command", "")
            return f"⚙️ Komut çalıştırılıyor: {cmd[:50]}"
        elif func_name == "generate_image":
            prompt = args.get("prompt", "")[:60]
            return f"🖼️ Görsel üretiliyor: {prompt}..."
        elif func_name == "generate_visual_prompt":
            subject = args.get("subject", "")[:60]
            return f"🎨 Görsel prompt yazılıyor: {subject}..."
        elif func_name == "generate_real_video":
            return f"🎥 Video üretiliyor (MP4)..."
        elif func_name == "calculate":
            expr = args.get("expression", "")[:80]
            return f"🧮 Hesaplanıyor: {expr}"
        else:
            return f"🔧 Araç kullanılıyor: {func_name}"
    
    def _get_tool_icon(self, func_name: str) -> str:
        """Get icon for tool."""
        icons = {
            "read_file": "📖",
            "write_file": "📝",
            "edit_file": "✏️",
            "list_files": "📁",
            "search_files": "🔍",
            "execute_command": "⚙️",
            "generate_code": "💻",
            "generate_visual_prompt": "🎨",
            "generate_image": "🖼️",
            "generate_video_prompt": "🎬",
            "generate_real_video": "🎥",
            "web_search": "🌐",
            "search_learning": "🧠",
            "answer_question": "💬",
            "calculate": "🧮"
        }
        return icons.get(func_name, "🔧")
    
    def _summarize_tool_result(self, func_name: str, result: dict) -> str:
        """Summarize tool result for thinking display."""
        if not result.get("success"):
            return None
        
        try:
            if func_name == "list_files":
                items = result.get("items", [])
                dirs = sum(1 for i in items if i.get("type") == "directory")
                files = len(items) - dirs
                return f"{dirs} klasör, {files} dosya bulundu"
            
            elif func_name == "read_file":
                content = result.get("content", "")
                lines = content.count("\n") + 1
                return f"Dosya okundu: {lines} satır"
            
            elif func_name == "search_files":
                matches = result.get("matches", [])
                return f"{len(matches)} eşleşme bulundu"
            
            elif func_name in ("write_file", "edit_file"):
                return "İşlem başarılı"
            
            elif func_name == "execute_command":
                output = result.get("output", "")
                if output:
                    return f"Çıktı alındı ({len(output)} karakter)"
                return "Komut çalıştırıldı"
        
        except:
            pass
        
        return None
    
    def _detect_intent(self, query: str) -> str:
        """Detect intent category for brain recording."""
        q = query.lower()
        if any(kw in q for kw in ["kod", "code", "api", "script", "python", "javascript", "function", "hello world"]):
            return "code"
        if any(kw in q for kw in ["görsel", "visual", "midjourney", "resim", "prompt", "çizim"]):
            return "visual"
        if any(kw in q for kw in ["video", "film", "sahne", "veo", "sora", "runway", "sinematik"]):
            return "video"
        return "question"
    
    def _tools_payload(self) -> list:
        """Tool specs advertised to the LLM.

        When the active agent declares a tool allow-list we advertise ONLY those
        tools (this enforces the per-agent capability list instead of treating it
        as inert metadata). Falls back to all tools when the allow-list is empty
        or unknown so the agent is never left without tools.
        """
        allowed = getattr(self, "_active_tools", None)
        # None  => kısıt YOK (tüm araçlar).  []  => hiç araç YOK (en az yetki).
        if allowed is None:
            return list(TOOLS)
        if not isinstance(allowed, (list, tuple, set)):
            logger.warning(f"Invalid _active_tools type {type(allowed).__name__}; using full TOOLS")
            return list(TOOLS)
        if len(allowed) == 0:
            # Kodlama Yöneticisi salt-okuma adımlarında bunu kullanır: hiç araç yok.
            return []
        wanted = set(allowed)
        filtered = [t for t in TOOLS if t.get("function", {}).get("name") in wanted]
        if not filtered:
            unknown = sorted(wanted - {t.get("function", {}).get("name") for t in TOOLS})
            logger.warning(f"Agent tool allow-list matched nothing (unknown={unknown}); using full TOOLS")
            return list(TOOLS)
        return filtered

    def _allowed_tool_names(self) -> set:
        """executor'ın zorlayacağı etkin araç adları kümesi.

        _tools_payload() ile BİREBİR tutarlıdır: reklam edilen araç = izinli araç.
        None (kısıt yok) -> tüm araç adları; [] -> boş küme (hiç araç).
        """
        try:
            return {
                t.get("function", {}).get("name")
                for t in self._tools_payload()
                if t.get("function", {}).get("name")
            }
        except Exception as e:
            logger.warning(f"_allowed_tool_names hatası, kısıt uygulanmıyor: {e}")
            return set()

    def _safe_window(self, messages: List[Dict], max_messages: int = 20) -> List[Dict]:
        """Return a token-safe window of the conversation.

        Keeps the system message plus the most recent messages, advancing the
        cut point to a valid boundary (a user message or a plain assistant
        message) so we never start on an orphaned tool result — providers reject
        that. Also caps total characters so a few huge tool outputs cannot blow
        past the provider's per-request token limit (the tool specs alone
        already cost ~2.8k tokens).
        """
        if not messages:
            return messages
        # messages[0] is system in our chat() flow; tolerate missing system.
        if isinstance(messages[0], dict) and messages[0].get("role") == "system":
            system = messages[0]
            rest = messages[1:]
        else:
            system = None
            rest = list(messages)
        if len(rest) <= max_messages:
            window = list(rest)
        else:
            start = len(rest) - max_messages
            while start < len(rest):
                m = rest[start]
                role = m.get("role") if isinstance(m, dict) else None
                if role == "user":
                    break
                if role == "assistant" and not m.get("tool_calls"):
                    break
                start += 1
            window = list(rest[start:])

        def _msg_len(m) -> int:
            try:
                return len(json.dumps(m, ensure_ascii=False))
            except Exception:
                return len(str(m))

        # Truncate any single oversized turn (huge tool output) to ~8k chars.
        trimmed = []
        for m in window:
            if isinstance(m, dict) and isinstance(m.get("content"), str) and len(m["content"]) > 8000:
                m = dict(m)
                m["content"] = m["content"][:8000] + "\n…[kırpıldı: çok uzun çıktı]"
            trimmed.append(m)
        window = trimmed

        total = sum(_msg_len(m) for m in window)
        while len(window) > 2 and total > 28000:
            window.pop(0)
            while window:
                r0 = window[0].get("role") if isinstance(window[0], dict) else None
                if r0 == "user":
                    break
                if r0 == "assistant" and not window[0].get("tool_calls"):
                    break
                window.pop(0)
            total = sum(_msg_len(m) for m in window)
        # Never end on assistant(tool_calls) without its tool answers.
        while window:
            last = window[-1]
            if isinstance(last, dict) and last.get("role") == "assistant" and last.get("tool_calls"):
                window.pop()
            else:
                break
        # Never start on a tool message whose assistant call was cut off.
        while window and isinstance(window[0], dict) and window[0].get("role") == "tool":
            window.pop(0)
        return ([system] if system is not None else []) + window

    # ------------------------------------------------------------------
    # PROJE İNŞA FALLBACK (deterministik dosya üretimi)
    # ------------------------------------------------------------------

    @staticmethod
    def _is_build_request(message: str) -> bool:
        """Kullanıcı bir site/uygulama/proje mi inşa etmemi istedi?"""
        q = _norm_tr(message)
        nouns = ("site", "web", "uygulama", "app", "proje", "dashboard",
                 "landing", "oyun", "arayüz")
        verbs = ("yap", "kaydet", "oluştur", "olustur", "tasarla", "geliştir",
                 "gelistir", "üret", "uret", "kur", "başlat")
        return any(k in q for k in nouns) and any(k in q for k in verbs)

    def _detect_save_target(self, message: str):
        """İstekte geçen kayıt hedefini belirle.

        "masa üstünde M klasörüne kaydet" -> (C:\\Users\\<ad>\\Desktop\\M, True)
        "ödev Klasörüne kaydet"           -> (<çalışma kökü>\\ödev, True)
        kural yok                          -> (None, False)
        """
        q = re.sub(r"\s+", " ", _norm_tr(message))
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        folder = ""
        m = re.search(r"([\wçğıöşü.\-]{1,24}?)\s*klas", q)
        if m:
            folder = re.sub(r"^(?:ve|bir|adlı|adli|isimli)\s+", "", m.group(1))
            folder = re.sub(r"[^\w\-.]", "", folder).strip(".")
        on_desktop = any(k in q for k in (
            "masaüst", "masaüstü", "masa üst", "masa ust", "masaust", "desktop"))
        if on_desktop:
            return os.path.join(desktop, folder or "nexus-proje"), True
        if folder and folder not in (
            "ve", "bir", "yap", "kaydet", "olustur", "oluştur", "site",
            "proje", "uygulama", "web", "app",
        ):
            return os.path.join(self.tools.working_dir or os.getcwd(), folder), True
        return None, False

    def _persist_project(self, path: str) -> None:
        """Proje kökünü araç + arayüz katmanlarına bildir (özet: dosya ağacı)."""
        try:
            os.environ["NEXUS_WORKING_DIR"] = path
        except Exception:
            pass
        try:
            import fs_routes as _fs
            _fs._current_workdir = path
            _fs._project_open = True
        except Exception:
            pass
        try:
            import project_routes as _pr
            _pr.WORKING_DIR = path
        except Exception:
            pass
        try:
            self.tools.working_dir = path
        except Exception:
            pass

    async def _local_oneshot(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Araçsız TEK atışlı yerel model çağrısı; ham metin döndürür.

        Model yine araç JSON'u basarsa içinden düz yanıtı kurtarır;
        başarısızlıkta boş metin döner (çağıran fallback karar verir).
        """
        import local_llm

        base_url = (self.llm_config.base_url
                    or local_llm.configured_url()
                    or "http://127.0.0.1:11434/v1").rstrip("/")
        mdl = (getattr(self, "_active_model", None) or self.llm_config.model
               or local_llm.model_name() or "qwen2.5:3b")
        if max_tokens is None:
            try:
                max_tokens = max(
                    512, min(int(os.getenv("NEXUS_LOCAL_LLM_MAX_TOKENS", "2048")), 8192)
                )
            except ValueError:
                max_tokens = 2048
        try:
            tout = max(120.0, float(os.getenv("NEXUS_LOCAL_LLM_TIMEOUT", "300")))
        except ValueError:
            tout = 300.0
        try:
            res = await local_llm.chat(
                [{"role": "user", "content": prompt}],
                model=mdl, base_url=base_url, temperature=0.2,
                max_tokens=max_tokens, timeout=tout,
                tools=None, tool_choice=None,
            )
            if isinstance(res, dict) and res.get("success"):
                data = res.get("data") or {}
                choices = data.get("choices") or []
                if choices:
                    content = ((choices[0] or {}).get("message") or {}).get("content") or ""
                    _calls, final_text = _extract_tool_json_calls(content, set())
                    return final_text or content
        except Exception as exc:
            logger.warning("Tek atışlı yerel çağrı başarısız: %s", exc)
        return ""

    async def _oneshot_project_text(self, user_message: str) -> str:
        """Araçsız TEK atışlı proje üretimi: yalnız ``### DOSYA`` belirtimi döndür."""
        spec = (
            "SEN KOD ÜRETİCİSİN. Hiçbir araç çağırma, araç çağrısı JSON'u YAZMA, "
            "açıklama yapma.\n"
            "İsteğe göre ÇALIŞAN bir proje üret ve ÇIKTIYI TAM OLARAK şu biçimde ver:\n"
            "### DOSYA: index.html\n```html\n(HTML kodu)\n```\n"
            "### DOSYA: styles.css\n```css\n(CSS kodu)\n```\n"
            "### DOSYA: script.js\n```js\n(JS kodu)\n```\n"
            "Web sitesi isteklerinde index.html + styles.css + script.js üret.\n"
            "Python isteklerinde main.py üret. Kod eksiksiz ve çalışır olsun.\n\n"
            f"İSTEK: {user_message}\n"
            "Yalnızca yukarıdaki biçimde dosyaları döndür, başka hiçbir metin yazma."
        )
        return await self._local_oneshot(spec)

    _FILE_LABEL_RE = re.compile(
        r"^[>\s*`#_-]*(?:###\s*)?(?:dosya|file|filename|dosya adı|dosya adi|path)"
        r"\s*[:=]?\s*[`\"']?([\w.\- /\\]{1,100}?)[`\"']?\s*$",
        re.IGNORECASE,
    )
    _FENCE_RE = re.compile(r"```([a-zA-Z0-9_+\-]*)\s*\n(.*?)```", re.DOTALL)

    @classmethod
    def _default_file_name(cls, lang: str, used: set) -> str:
        l = (lang or "").lower()
        if "html" in l:
            cand = "index.html"
        elif "css" in l:
            cand = "styles.css"
        elif "jsx" in l:
            cand = "App.jsx"
        elif "json" in l:
            cand = "data.json"
        elif "ts" in l:
            cand = "app.ts"
        elif "js" in l or "javascript" in l:
            cand = "script.js"
        elif "py" in l or "python" in l:
            cand = "main.py"
        elif "md" in l:
            cand = "README.md"
        elif "sql" in l:
            cand = "schema.sql"
        else:
            cand = "main.txt"
        base, ext = os.path.splitext(cand)
        n = 2
        while cand in used:
            cand = f"{base}{n}{ext}"
            n += 1
        return cand

    @classmethod
    def _extract_fenced_files(cls, text: str):
        """``### DOSYA: <yol>`` + kod çiti ikililerini ayıkla."""
        if not text:
            return []
        pairs = []
        for m in cls._FENCE_RE.finditer(text):
            lang = (m.group(1) or "").strip()
            code = (m.group(2) or "").replace("\r\n", "\n").strip()
            if not code or len(code) > 120_000:
                continue
            before = text[: m.start()].rstrip()
            lines = before.splitlines()
            last_line = lines[-1].strip() if lines else ""
            lm = cls._FILE_LABEL_RE.match(last_line)
            rel = ""
            if lm:
                rel = re.sub(r"^\./", "", lm.group(1).strip().replace("\\", "/")).strip()
            if not rel:
                rel = cls._default_file_name(lang, {p[0] for p in pairs})
            # Güvenlik: göreli yolu tabana hapsit (mutlak/üst-dizin yollarını soy)
            rel = re.sub(r"^(/|[a-zA-Z]:)", "", rel).lstrip("/\\")
            rel = os.path.normpath(rel).replace("\\", "/")
            if rel.startswith("..") or rel in ("", ".", "/"):
                continue
            if len(pairs) >= 12:
                break
            rel = rel or cls._default_file_name(lang, {p[0] for p in pairs})
            pairs.append((rel, code))
        return pairs

    @classmethod
    def _template_router(cls, user_message: str):
        """İsteği hazır şablon alanına eşler: food / prayer / student / None."""
        q = _ascii_tr(user_message)
        if any(k in q for k in ("namaz", "vakit", "ezan", "prayer",
                                "imsak", "iftar", "teravih")):
            return "prayer"
        if "ogrenci" in q or "ogretmen" in q:
            return "student"
        if any(k in q for k in ("yemek", "restoran", "lokanta", "kebap",
                                "pizza", "fast food", "kafe", "kahvalti")):
            return "food"
        return None

    @classmethod
    def _template_project(cls, user_message: str):
        """LLM biçime uygun yanıt üretemezse: hazır, TAM ÇALIŞAN proje."""
        domain = cls._template_router(user_message)
        if domain == "prayer":
            return [
                ("index.html", _PRAYER_TEMPLATE_HTML),
                ("styles.css", _PRAYER_TEMPLATE_CSS),
                ("script.js", _PRAYER_TEMPLATE_JS),
                ("manifest.json", _PRAYER_TEMPLATE_MANIFEST),
            ]
        if domain == "student":
            return [
                ("main.py", _STUDENT_TEMPLATE_PY),
                ("README.md", _STUDENT_TEMPLATE_README),
            ]
        if domain == "food":
            return [
                ("index.html", _FOOD_TEMPLATE_HTML),
                ("styles.css", _FOOD_TEMPLATE_CSS),
                ("script.js", _FOOD_TEMPLATE_JS),
            ]
        return [
            ("index.html", _BUILD_TEMPLATE_HTML),
            ("styles.css", _BUILD_TEMPLATE_CSS),
            ("script.js", _BUILD_TEMPLATE_JS),
        ]

    # ------------------------------------------------------------------
    # MEVCUT PROJE ÜZERİNDE DÜZENLEME (ekle/sil/değiştir/güncelle)
    # ------------------------------------------------------------------

    _EDITABLE_EXTS = (".html", ".css", ".js", ".py", ".json", ".md")
    _EDIT_KEYWORDS = (
        "ekle", "ekli", "sil", "çık", "cik", "çıkar", "cikar",
        "kaldır", "kaldir", "değiştir", "degistir", "güncelle", "guncelle",
        "düzelt", "duzelt", "yenile", "büyüt", "buyut", "küçült", "kucult",
    )
    _EDIT_SOFT_KEYWORDS = ("renk", "başlık", "baslik", "font", "logo")

    def _project_root_for(self, message: str, require_project: bool = False):
        """Düzenlenecek proje kökü.

        Öncelik: istekte adı geçen klasör > görev-yerel kök (kodlama
        zinciri) > çalışma kökü (UI'nin açık projesi). ``require_project``
        ise kökte ``index.html`` aranır; kök bir proje değilse None döner.
        """
        try:
            target, promoted = self._detect_save_target(message)
        except Exception:
            target, promoted = None, False
        if promoted and target and os.path.isdir(target):
            root = target
        else:
            try:
                from tool_executor import task_working_dir as _twd
                ctx_root = _twd.get()
            except Exception:
                ctx_root = None
            tools_dir = getattr(getattr(self, "tools", None), "working_dir", None)
            root = ctx_root or tools_dir or os.getcwd()
        root = os.path.abspath(str(root))
        if not os.path.isdir(root):
            return None
        if require_project:
            if root == _APP_ROOT:
                # Uygulamanın KENDİ kökü bir kullanıcı projesi değildir;
                # yanlışlıkla NEXUS arayüz dosyalarını düzenlemesin.
                return None
            if not os.path.exists(os.path.join(root, "index.html")):
                return None
        return root

    def _is_edit_request(self, message: str) -> bool:
        """Yeni site inşası değil, MEVCUT projeye küçük müdahale mi?

        "menüye adana ekle" / "renkleri değiştir" tarzı istekler ve diskte
        proje varsa True; "yemek sitesi yap..." tarzı taze inşa sinyali
        (inşa ismi + fiili aynı anda) varsa False.
        """
        q = _norm_tr(message)
        if not q:
            return False
        strong = any(k in q for k in self._EDIT_KEYWORDS)
        soft = any(k in q for k in self._EDIT_SOFT_KEYWORDS)
        if not (strong or soft):
            return False
        if not self._project_root_for(message, require_project=True):
            return False
        nouns = ("site", "web", "uygulama", "app", "proje", "dashboard",
                 "landing", "oyun", "arayüz")
        verbs = ("yap", "kaydet", "oluştur", "olustur", "tasarla",
                 "geliştir", "gelistir", "üret", "uret", "kur")
        fresh_build = any(n in q for n in nouns) and any(v in q for v in verbs)
        return not fresh_build

    # ------------------------------------------------------------------
    # KENDİ KENDİNİ İYİLEŞTİRME: deterministik hızlı düzen + öz denetim
    # ------------------------------------------------------------------

    _COLOR_MAP = {
        "yesil": "#2e7d32", "mavi": "#1565c0", "kirmizi": "#c62828",
        "turuncu": "#ef6c00", "mor": "#6a1b9a", "pembe": "#ad1457",
        "sari": "#f9a825", "gri": "#546e7a", "siyah": "#212121",
        "kahverengi": "#5d4037",
    }

    _EDIT_TARGET_TOKENS = {
        "klasorundeki", "klasorune", "klasorde", "klasore",
        "siteye", "sitede", "site", "menuye", "menude", "menu",
        "listeye", "listede", "sayfaya", "sayfada", "uygulamaya",
        "uygulamada", "projeye", "dosyaya", "dosyada", "yap",
        "liste", "icin", "bir", "tane", "yeni", "olsun", "olur",
    }

    def _deterministic_edits(self, message: str, root: str):
        """Küçük yerel modele güvenmeden UYGULANABİLİR basit düzenleri
        kodla yapar; ok (dosya-adı, içerik, not) listesi döner.

        Desteklenenler:
          * renk değişimi: styles.css içinde ``--brand`` CSS değişkeni.
          * menüye ürün ekleme: script.js içinde ``const MENU = [...]``.
        """
        q = _ascii_tr(message)
        out: list = []
        notes: list = []
        source = {}
        for name in ("styles.css", "script.js"):
            p = os.path.join(root, name)
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                        source[name] = fh.read()
                except Exception:
                    source[name] = ""

        # --- 1) RENK DEĞİŞİMİ --------------------------------------------
        color_word = next((w for w in self._COLOR_MAP if w in q), None)
        wants_color = ("renk" in q or "tema" in q or color_word is not None)
        if wants_color and color_word and "styles.css" in source:
            css = source["styles.css"]
            hexv = self._COLOR_MAP[color_word]
            new_css = re.sub(r"(--brand\s*:\s*)#[0-9a-fA-F]{3,8};",
                             r"\g<1>" + hexv + ";", css, count=1)
            if new_css != css:
                source["styles.css"] = new_css
                out.append(("styles.css", new_css))
                notes.append(f"🎨 {color_word} → ana marka rengi {hexv} yapıldı.")

        # --- 2) MENÜYE ÜRÜN EKLEME ---------------------------------------
        if "ekle" in q and "script.js" in source:
            js = source["script.js"]
            anchor = js.find("const MENU")
            if anchor != -1:
                stop = js.find("];", anchor)
                if stop != -1:
                    # "ekle"den ÖNCEKİ kelimelerden ürün adını topla
                    # (sonraki kelimeler "renkleri yeşil olsun" gibi ikinci
                    # isteğe ait olabilir).
                    toks = re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", message)
                    pos_ekle = next(
                        (i for i, t in enumerate(toks)
                         if _ascii_tr(t) == "ekle"), -1)
                    toks = toks[:pos_ekle] if pos_ekle != -1 else toks
                    stopwords = {
                        _ascii_tr(w) for w in (
                            "EKLE", "EKLEBILIR", "SİTEYE", "SİTEDE", "MENÜYE",
                            "MENÜDE", "KLASÖRÜNDEKİ", "KLASÖRÜNE", "SİTENE",
                            "UYGULAMAYA", "UYGULAMADA", "PROJEYE", "PROJEDE",
                            "MASA", "ÜSTÜNDE", "MASAAÜSTÜ", "MASAÜSTÜ", "VE",
                            "YAP", "OLSUN", "İSTİYORUM", "LÜTFEN", "BANA", "BENİ",
                        )
                    }
                    picked = []
                    for t in reversed(toks):
                        tlow = _ascii_tr(t)
                        if tlow in stopwords or tlow in self._EDIT_TARGET_TOKENS:
                            if picked:      # hedef kelimeye ulaşıldı; ad bitti
                                break
                            continue
                        if len(t) < 2 or (picked and len(" ".join(picked)) > 24):
                            break
                        picked.insert(0, t)
                    ad = " ".join(picked).strip().title() or "Yeni Lezzet"
                    ids = [int(m.group(1)) for m in
                           re.finditer(r"id\s*:\s*(\d+)", js[anchor:stop])]
                    yeni = {
                        "id": (max(ids) + 1) if ids else 99,
                        "ad": ad,
                        "kategori": "Ana Yemek",
                        "fiyat": 95,
                        "emoji": "🍽️",
                    }
                    ek = ('  { id:%d, ad:"%s", kategori:"%s", fiyat:%d, emoji:"%s" },'
                          % (yeni["id"], yeni["ad"], yeni["kategori"],
                             yeni["fiyat"], yeni["emoji"]))
                    yeni_js = js[:stop] + ek + "\n" + js[stop:]
                    source["script.js"] = yeni_js
                    out.append(("script.js", yeni_js))
                    notes.append(f"🍽️ Menüye “{ad}” eklendi (₺{yeni['fiyat']}).")
        return (out, notes) if out else None

    @staticmethod
    def _self_review(root: str):
        """Üretilen projeyi hızlıca denetler: (temiz, sorunlar)."""
        issues: list = []
        idx = os.path.join(root, "index.html")
        if os.path.exists(idx):
            try:
                html = open(idx, encoding="utf-8", errors="ignore").read()
            except Exception as exc:
                return False, [f"index.html okunamadı: {exc}"]
            if "<body" not in html or "</html>" not in html:
                issues.append("HTML iskeleti eksik")
            for ref in re.findall(r'(?:src|href)="([^"\s]+\.(?:css|js))"', html):
                if not os.path.exists(os.path.join(root, ref)):
                    issues.append(f"eksik referans: {ref}")
        for name in (os.listdir(root) if os.path.isdir(root) else []):
            if name.endswith(".py"):
                try:
                    src = open(os.path.join(root, name), encoding="utf-8").read()
                    compile(src, name, "exec")  # disk dokunmadan sözdizimi denetimi
                except Exception as exc:
                    issues.append(f"{name}: {exc}")
        return (not issues), issues

    def _edit_failure_response(self, user_message: str) -> Dict:
        """Düzenleme uygulanamadı: dosyalar DEĞİŞMEDEN dürüst yanıt.

        Yeniden şablon üretimi KULLANILMAZ — kullanıcının önceki
        değişiklikleri silinmesin.
        """
        root = self._project_root_for(user_message)
        target_line = f"\n📁 Klasör: {root}" if root else ""
        return {
            "files": [],
            "mode": "edit-failed",
            "response": (
                "⚠️ Değişikliği uygulayamadım: yerel model bu isteği "
                "uygulanabilir dosya biçimine çeviremedi ve mevcut dosyalarını "
                "değiştirmedim." + target_line + "\nİsteği tek bir değişiklik "
                "hâlinde yazarsan tekrar denerim (örn. \"menüye adana "
                "kebap ekle\")."
            ),
            "notes": ["Model düzenleme çıktısı biçime uymadı; dosyalar değişmedi."],
        }

    @staticmethod
    def _write_files_into(base_root: str, files):
        """(rel, içerik) listesini ``base_root`` altına yaz; (abs, rel) döndür."""
        written = []
        for rel, content in files:
            try:
                abs_path = os.path.join(base_root, *rel.split("/"))
                parent = os.path.dirname(abs_path) or base_root
                os.makedirs(parent, exist_ok=True)
                with open(abs_path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(content)
                written.append((abs_path, rel))
            except Exception as exc:
                logger.warning("Dosya yazılamadı %s: %s", rel, exc)
        return written

    async def _edit_build_files(self, user_message: str, max_changed: int = 8):
        """Mevcut projeyi oku, değişikliği modelle uygula, üzerine yaz.

        Taze üretim YOK: model yalnızca değişen dosyaların tamamını döndürür;
        başarısızsa None (çağıran dürüst mesaj verir), dosyalar korunur.
        """
        root = self._project_root_for(user_message, require_project=True)
        if not root:
            return None

        # ---- ADIM 1: KENDİ KENDİNİ DÜZELTME (deterministik hızlı yol) -----
        # Küçük yerel model bu işi dakikalar sonra bile biçimde yapamıyor;
        # basit değişiklikler (renk, menü ekleme) kod ile SİNYELDE yapılır.
        try:
            det = self._deterministic_edits(user_message, root)
        except Exception as exc:
            logger.warning("Deterministik edit hatası: %s", exc)
            det = None
        if det:
            files_det, det_notes = det
            written = self._write_files_into(root, files_det)
            if written:
                ok, sorunlar = self._self_review(root)
                detek = "" if ok else "\n⚠️ Öz denetim: " + "; ".join(sorunlar)
                listing = "\n".join(f"- {rel}" for _, rel in written)
                return {
                    "files": [rel for _, rel in written],
                    "response": (
                        f"✏️ Güncellendi!\n📁 Klasör: {root}\n\n"
                        f"Değişen dosyalar:\n{listing}\n\n"
                        + "\n".join(det_notes)
                        + (f"\n\n🧪 Kendi kontrol: temiz ✓" if ok else detek)
                        + "\n\nBaşka bir değişiklik istersen söylemen yeterli."
                    ),
                    "notes": list(det_notes),
                    "mode": "edit-deterministic",
                    "base_root": root,
                }

        lang_by_ext = {
            ".html": "html", ".css": "css", ".js": "javascript",
            ".py": "python", ".json": "json", ".md": "markdown",
        }
        try:
            names = sorted(
                n for n in os.listdir(root)
                if os.path.isfile(os.path.join(root, n))
                and os.path.splitext(n)[1].lower() in self._EDITABLE_EXTS
            )
        except Exception:
            return None
        ctx_parts = []
        original = {}
        for n in names[:12]:
            p = os.path.join(root, n)
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                    txt = fh.read()
            except Exception:
                continue
            if len(txt) > 60_000:
                txt = txt[:60_000] + "\n…(kesildi)"
            original[n] = len(txt)
            ext = os.path.splitext(n)[1].lower()
            ctx_parts.append(
                f"### DOSYA: {n}\n```{lang_by_ext.get(ext, '')}\n{txt}\n```"
            )
        if not ctx_parts:
            return None

        notes: List[str] = []
        spec = (
            "SEN KOD DÜZENLEYİCİSİN. Araç çağırma, araç çağrısı JSON'u YAZMA, "
            "açıklama yapma.\n"
            "Aşağıda mevcut proje dosyaları veriliyor. Değişiklik isteğini "
            "dosyalara uygula ve SADECE değişen dosyaların TAM güncel içeriğini "
            "şu biçimde döndür:\n"
            "### DOSYA: index.html\n```html\n(dosyanın güncel TAM İÇERİĞİ)\n```\n"
            "ÖNEMLİ: Siteyi SIFIRDAN KURMA. Var olan tüm bölümleri, özellikleri, "
            "CSS sınıflarını, içerikleri ve tasarımı KORU; yalnızca istenen "
            "değişiklikleri uygula. Değişmeyen dosyaları verme. Parça verme; "
            "dosyanın tamamını yaz.\n\n"
            f"DEĞİŞİKLİK İSTEĞİ: {user_message}\n\n"
            "MEVCUT DOSYALAR:\n" + "\n\n".join(ctx_parts)
        )
        text = await self._local_oneshot(spec)
        files = self._extract_fenced_files(text or "")

        # ---- ADIM 2: KENDİ KENDİNİ DÜZELTME (LLM, 2. deneme) -------------
        # İlk çıktı biçime uymadıysa model, önceki ÇÖP çıktısını görerek
        # düzeltilmiş biçim üretmeye bir kez daha çalışır.
        if not files:
            retry_spec = (
                "ÖNCEKİ DENEMEN GEÇERSİZDİ: biçim yerine açıklama/çöp yazdın.\n"
                "SADECE şu biçimde yanıt ver; başka HİÇBİR metin yok:\n"
                "### DOSYA: index.html\n```html\n(dosyanın güncel TAM İÇERİĞİ)\n```\n"
                "Örnek çıktının biçimi yukarıdadır; değişen HER dosya için "
                "bir blok yaz ve dosyanın tamamını ver.\n\n"
                f"DEĞİŞİKLİK İSTEĞİ: {user_message}\n\n"
                "MEVCUT DOSYALAR:\n" + "\n\n".join(ctx_parts)
            )
            text2 = await self._local_oneshot(retry_spec, max_tokens=2048)
            files = self._extract_fenced_files(text2 or "")
            if files:
                notes.append("Model ilk denemede biçime uymadı; ikinci denemede düzeltti.")
        if not files:
            return None

        # Kalite kapısı: ana HTML %40'tan fazla kısalmışsa kesilme say, iptal.
        for rel, code in list(files):
            base = os.path.basename(rel).lower()
            old_len = original.get(base)
            if (base.endswith(".html") and old_len
                    and len(code.strip()) < int(old_len * 0.6)):
                logger.warning(
                    "Düzenleme şüpheli kısalma: %s %d -> %d (reddedildi)",
                    rel, old_len, len(code.strip()),
                )
                return None
        files = files[:max_changed]

        written = self._write_files_into(root, files)
        if not written:
            return None

        ok, sorunlar = self._self_review(root)
        if ok:
            notes.append("🧪 Kendi kontrol: temiz ✓ (referanslar ve iskelet sağlam)")
        else:
            notes.append("⚠️ Öz denetim sorunları: " + "; ".join(sorunlar))

        listing = "\n".join(f"- {rel}" for _, rel in written)
        response = (
            f"✏️ Güncellendi!\n📁 Klasör: {root}\n\n"
            f"Değişen dosyalar:\n{listing}\n\n"
            "Başka bir değişiklik istersen söylemen yeterli."
        )
        return {
            "files": [rel for _, rel in written],
            "response": response,
            "notes": notes,
            "mode": "edit",
            "base_root": root,
        }

    async def _smart_build_or_edit(self, user_message: str, draft_response: str = ""):
        """Site/uygulama istekleri için tek giriş noktası.

        * Düzenleme isteği + diskte proje -> mevcut dosyaları düzenle.
        * Diğer inşa istekleri -> yeni proje/şablon üret.
        * Düzenleme uygulanamazsa dosyalar DEĞİŞMEDEN dürüst yanıt.
        """
        try:
            edit_like = bool(self._is_edit_request(user_message))
        except Exception:
            edit_like = False
        if edit_like:
            try:
                ed = await self._edit_build_files(user_message)
            except Exception as exc:
                logger.warning("Düzenleme akışı hatası: %s", exc)
                ed = None
            if ed:
                return ed
            return self._edit_failure_response(user_message)
        bf = await self._write_build_files(user_message, draft_response)
        if bf:
            bf.setdefault("mode", "build")
        return bf

    async def _write_build_files(self, user_message: str, draft_response: str = ""):
        """Proje inşa isteğini GERÇEK dosyalara döker (deterministik kanat).

        1) Draft yanıtta ``### DOSYA`` bloklarını dene.
        2) Yoksa tek atışlı araçsız LLM üretimi dene.
        3) O da olmazsa hazır şablonu yaz. Her durumda diskte dosya vardır.

        Yazım ToolExecutor yerine DOĞRUDAN yapılır: hedef dizin
        (kullanıcının açık isteği, örn. Masaüstü\\M) hangi bağlamdan
        çağrılırsa çağrılsın birebir korunur.
        """
        target, promoted = self._detect_save_target(user_message)
        try:
            from tool_executor import task_working_dir as _twd
            ctx_root = _twd.get()
        except Exception:
            ctx_root = None
        base_root = (
            target if promoted and target
            else (ctx_root or self.tools.working_dir or os.getcwd())
        )
        base_root = os.path.abspath(str(base_root))
        if base_root == _APP_ROOT:
            # ŞablonN projeleri uygulamanın kendi klasörüne yazılmaz;
            # Masaüstü/NexusProjeler altına gider.
            base_root = os.path.join(
                os.path.expanduser("~"), "Desktop", "NexusProjeler"
            )

        notes: List[str] = []
        files = self._extract_fenced_files(draft_response or "")
        # BİLİNEN ALAN (yemek / namaz / öğrenci-giriş): küçük yerel model
        # zaten kalite kapısını geçemiyor ve dakikalar harcıyordu. Alan
        # şablonu direkt yazılır: hem kaliteli hem hızlı (skndeler içinde).
        if not files and os.getenv("NEXUS_DIRECT_TEMPLATES", "1") != "0":
            domain = self._template_router(user_message)
            if domain:
                files = self._template_project(user_message)
                notes.append(
                    "Hızlı üretim: " + domain + " alanı için hazır gelişmiş "
                    "şablon doğrudan yazıldı. Değişiklik istersen söylemen "
                    "yeterli (örn. 'adana kebap ekle', 'renkleri yeşil yap')."
                )
        if not files:
            text = await self._oneshot_project_text(user_message)
            files = self._extract_fenced_files(text or "")
        if not files:
            files = self._template_project(user_message)
            notes.append(
                "Model biçime uygun dosya üretmeyi başaramadı; hazır şablon "
                "ile proje oluşturuldu. İsteğin ayrıntısını (konu, renk, "
                "bölümler) yazarsan model üretimini tekrar deneriz."
            )
        if not files:
            return None

        # ---- KALİTE KAPISI (deterministik) ---------------------------------
        # Küçük yerel modeller bazen birkaç karakterlik taslak döndürür ve
        # çöp .py/.js artıkları basar. Web projesinde ana HTML çok kısaysa
        # üretim başarısız sayılır; hazır şablon devreye girer.
        html_entries = [f for f in files if f[0].lower().endswith(".html")]
        if html_entries:
            files = [
                (rel, code) for rel, code in files
                if rel.lower().endswith((".html", ".css"))
                or len(code.strip()) >= 200
            ]
            primary = max(html_entries, key=lambda f: len(f[1]))[1]
            if len(primary.strip()) < 1500:
                files = self._template_project(user_message)
                notes.append(
                    "Yerel modelin üretimi çok kısa ve bozuktu; kalite "
                    "kapısı hazır şablonu devreye aldı."
                )
        if not files:
            return None

        if promoted and target:
            try:
                os.makedirs(target, exist_ok=True)
                self._persist_project(target)
            except Exception:
                return None

        written = self._write_files_into(base_root, files)
        if not written:
            return None

        # ---- KENDİ KENDİNİ DENETLEME ---------------------------------------
        try:
            ok, sorunlar = self._self_review(base_root)
            if ok:
                notes.append("🧪 Kendi kontrol: temiz ✓ (referanslar/iskelet/derleme sağlam)")
            else:
                notes.append("⚠️ Öz denetim sorunları: " + "; ".join(sorunlar))
        except Exception as exc:  # kontrol asla üretimi engellemesin
            logger.warning("Öz denetim çalışamadı: %s", exc)

        listing = "\n".join(f"- {rel}" for _, rel in written)
        entry = next(
            (rel for _, rel in written if os.path.basename(rel) == "index.html"),
            written[0][1],
        )
        target_note = f"\n📁 Hedef klasör: {base_root}" if promoted else ""
        response = (
            "✅ Proje hazır! " + target_note
            + "\n\nOluşturulan dosyalar:\n" + listing
            + f"\n\nTarayıcıda açmak için \"{entry}\" dosyasına çift tıkla "
            + "(veya adres çubuğuna dosya yolunu yapıştır). İstersen "
            + "güncelleme söylemen yeterli: renkler, menü, bölümler..."
        )
        return {
            "files": [rel for _, rel in written],
            "response": response,
            "notes": notes,
            "base_root": base_root,
        }

    async def _call_llm(self, messages: List[Dict]) -> Dict:
        """Call the LLM API with tools. Comprehensive multi-provider, multi-model fallback + response validation."""
        import httpx
        import json as json_mod

        # Keep the request within provider token limits (see _safe_window).
        messages = self._safe_window(messages)
        
        # JSON Schema for response validation
        RESPONSE_SCHEMA = {
            "type": "object",
            "required": ["choices"],
            "properties": {
                "choices": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["message"],
                        "properties": {
                            "message": {
                                "type": "object",
                                "required": ["role", "content"],
                                "properties": {
                                    "role": {"type": "string", "enum": ["assistant"]},
                                    "content": {"type": ["string", "null"]},
                                    "tool_calls": {
                                        "type": ["array", "null"],
                                        "items": {
                                            "type": "object",
                                            "required": ["id", "type", "function"],
                                            "properties": {
                                                "id": {"type": "string"},
                                                "type": {"type": "string", "enum": ["function"]},
                                                "function": {
                                                    "type": "object",
                                                    "required": ["name", "arguments"],
                                                    "properties": {
                                                        "name": {"type": "string"},
                                                        "arguments": {"type": "string"}
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            },
                            "finish_reason": {"type": ["string", "null"]}
                        }
                    }
                }
            }
        }
        
        # Always load latest config from model_config.json
        self._refresh_llm_config()
        
        model = getattr(self, '_active_model', None) or self.llm_config.model
        return await self._call_local_primary(messages, model)

    async def _call_local_primary(self, messages: List[Dict], model: str = None) -> Dict:
        """Seçili yerel Ollama modelini birincil olarak çağırır."""
        import local_llm

        base_url = (self.llm_config.base_url
                    or local_llm.configured_url()
                    or "http://127.0.0.1:11434/v1").rstrip("/")
        mdl = (model or self.llm_config.model or local_llm.model_name()
               or "qwen2.5:3b").strip()

        if not local_llm.is_loopback(base_url):
            return {
                "success": False,
                "provider": "local",
                "model": mdl,
                "error": "Yerel model yalnızca localhost/127.0.0.1 adresinden çağrılabilir.",
            }

        try:
            local_max = int(os.getenv("NEXUS_LOCAL_LLM_MAX_TOKENS", "2048"))
        except ValueError:
            local_max = 2048
        local_max = max(64, min(local_max, 8192))
        try:
            local_timeout = float(os.getenv("NEXUS_LOCAL_LLM_TIMEOUT", "900"))
        except ValueError:
            local_timeout = 900.0
        tools = self._tools_payload()
        has_write_tool = any(
            t.get("function", {}).get("name") in ("write_file", "edit_file")
            for t in tools
        )
        token_cap = local_max if has_write_tool else min(local_max, 512)
        tool_names = {t.get("function", {}).get("name") for t in tools}
        tool_choice = "required" if tool_names == {"write_file"} else "auto"
        result = await local_llm.chat(
            messages,
            model=mdl,
            base_url=base_url,
            temperature=self.llm_config.temperature,
            max_tokens=min(int(self.llm_config.max_tokens or token_cap), token_cap),
            timeout=max(30.0, local_timeout),
            tools=tools or None,
            tool_choice=tool_choice,
        )
        result.setdefault("provider", "local")
        result.setdefault("model", mdl)
        if result.get("success"):
            if result.get("model"):
                self.llm_config.model = result["model"]
            logger.info("Yerel model birincil çağrısı başarılı: %s", result.get("model"))
            return result
        else:
            logger.warning("Yerel model çağrısı başarısız: %s", result.get("error", "bilinmeyen hata"))
            # Sadece yerel alternatif modelleri dene
            return await self._fallback_chain(messages, failed_provider="local", failed_model=mdl)

    async def _fallback_chain(self, messages: List[Dict], failed_provider: str = None, failed_model: str = None, rate_limited: bool = False) -> Dict:
        """
        Yerel fallback zinciri:
        Yalnızca kurulu diğer yerel Ollama modellerini dener, bulut aranmaz.
        """
        messages = self._safe_window(messages)
        try:
            import local_llm

            # Yerel model kapalıysa (loopback olmayan URL) hiç denemeden
            # kural tabanlı yanıta geç; buluta asla sıçramaz.
            if not local_llm.is_enabled():
                logger.info("Yerel model kapalı; kural tabanlı yanıta geçiliyor")
                return await self._fallback_response(messages)

            info = await local_llm.detect(timeout=2.0)
            models = info.get("models") or []
            alt_models = [m for m in models if isinstance(m, str) and m != failed_model]
            for alt in alt_models:
                logger.info("Yerel alternatif deneniyor: %s", alt)
                base_url = (self.llm_config.base_url or local_llm.configured_url() or "http://127.0.0.1:11434/v1").rstrip("/")
                res = await local_llm.chat(
                    messages,
                    model=alt,
                    base_url=base_url,
                    temperature=self.llm_config.temperature,
                    max_tokens=512,
                    timeout=60.0,
                    tools=self._tools_payload() or None,
                )
                if res.get("success"):
                    self.llm_config.model = alt
                    return res
        except Exception as e:
            logger.warning(f"Yerel fallback hatası: {e}")

        logger.warning("Tüm yerel modeller tükendi, kural tabanlı yanıta geçiliyor")
        return await self._fallback_response(messages)


    async def _fallback_response(self, messages: List[Dict]) -> Dict:
        """
        Fallback when no API key or LLM error.
        Rule-based agent enhanced with BRAIN predictions for smarter tool selection.
        """
        # Get last user message (keep original case for prompts)
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")
                break
        
        # If a tool already ran in this loop, format its result
        for msg in reversed(messages):
            if msg.get("role") == "tool":
                try:
                    tool_data = json.loads(msg.get("content", "{}"))
                    if tool_data.get("success"):
                        if "code" in tool_data:
                            return self._llm_style(
                                f"İşte istediğiniz kod ({tool_data.get('language', 'python')}, "
                                f"{tool_data.get('mode', 'api')} modu):\n\n"
                                f"```{tool_data.get('language', 'python')}\n{tool_data['code']}\n```\n\n"
                                f"Bu kodu doğrudan kopyalayıp kullanabilirsiniz. Değişiklik ister misiniz?"
                            )
                        if "final_prompt" in tool_data:
                            return self._llm_style(
                                f"İşte oluşturduğum profesyonel prompt:\n\n"
                                f"```\n{tool_data['final_prompt']}\n```\n\n"
                                f"Bu prompt'u Midjourney, Stable Diffusion, DALL-E, Veo, Sora veya "
                                f"Runway'de doğrudan kullanabilirsiniz. Detay eklememi ister misiniz?"
                            )
                except Exception:
                    pass
        
        # --- BRAIN-ENHANCED Intent detection ---
        import re
        q = user_msg.lower()
        
        # Get brain predictions for this query
        brain_predictions = []
        if hasattr(self, 'brain') and self.brain:
            brain_predictions = self.brain.predict_best_tool(user_msg)
        
        def has_any(words):
            for w in words:
                if re.search(r"(?<![a-zçğıöşü])" + re.escape(w) + r"(?![a-zçğıöşü])", q):
                    return True
            return False
        
        # Strong keywords = explicitly names a tool/domain
        code_strong = ["kod", "code", "api", "script", "fonksiyon", "function", "program",
                       "python", "javascript", "typescript", "backend", "react", "component",
                       "fastapi", "flask", "express", "html", "css", "sql", "bash",
                       "hello world", "fibonacci", "sınf", "class", "endpoint", "rest"]
        visual_strong = ["görsel", "gorsel", "visual", "image", "resim", "midjourney",
                         "dall-e", "dalle", "stable diffusion", "çizim", "cizim", "poster",
                         "logo", "fotoğraf", "fotograf", "prompt"]
        video_strong = ["video", "film", "sahne", "scene", "timecode", "veo", "sora",
                        "runway", "sinematik", "cinematic", "trailer", "klip"]
        
        # Weak keywords = only count if no strong match
        code_weak = ["yaz", "yazdır", "oluştur", "olustur", "programla"]
        visual_weak = ["art", "tema", "çiz", "cyberpunk"]
        video_weak = ["lansman", "kamera hareket", "hareket"]
        
        is_code = has_any(code_strong)
        is_visual = has_any(visual_strong)
        is_video = has_any(video_strong)
        
        # BRAIN OVERRIDE: If brain strongly predicts a tool, trust it
        for tool, confidence in brain_predictions:
            if confidence > 0.75:
                if tool == "generate_code":
                    is_code = True
                elif tool == "generate_visual_prompt":
                    is_visual = True
                elif tool == "generate_video_prompt":
                    is_video = True
        
        if not (is_code or is_visual or is_video):
            if has_any(code_weak):
                is_code = True
            elif has_any(visual_weak):
                is_visual = True
            elif has_any(video_weak):
                is_video = True
        
        # Multi-tool: user wants more than one output
        if sum([is_code, is_visual, is_video]) >= 2:
            return await self._run_multi_tool(user_msg, q)
        
        if is_code:
            return await self._run_code_tool(user_msg, q)
        
        if is_visual:
            return await self._run_visual_tool(user_msg, q)
        
        if is_video:
            return await self._run_video_tool(user_msg, q)

        # Weather queries: use web search even in fallback
        if any(kw in q for kw in ["hava durumu", "hava nasıl", "hava nasil", "weather", "derece", "sıcaklık", "sicaklik", "yağmur", "yagmur", "kar", "rüzgâr", "ruzgar", "nem"]):
            try:
                results = await web_search_unified(user_msg, 3)
                if results:
                    snippets = []
                    for r in results:
                        snippet = r.get("snippet", "").strip()
                        if snippet:
                            snippets.append(snippet[:200])
                    if snippets:
                        combined = " | ".join(snippets[:3])
                        return self._llm_style(f"🌤️ **Hava durumu bilgisi (web araması):**\n\n{combined}\n\n*Kaynak: DuckDuckGo web araması*")
            except Exception:
                pass  # Fall through to generic answer

        # Question answering (rule-based knowledge)
        return self._llm_style(self._answer_question(user_msg))
    
    def _llm_style(self, content: str) -> Dict:
        """Wrap content in OpenAI-style response format."""
        return {
            "success": True,
            "data": {"choices": [{"message": {"content": content, "role": "assistant"}}]}
        }
    
    async def _run_code_tool(self, user_msg: str, q: str) -> Dict:
        """Autonomously pick language/mode and generate code."""
        language = "python"
        if any(kw in q for kw in ["javascript", " node", "npm", " js ", "js)", "react", "express"]):
            language = "javascript"
        elif "typescript" in q or " ts " in q:
            language = "typescript"
        elif any(kw in q for kw in ["bash", "shell", "terminal", "powershell"]):
            language = "bash"
        elif "sql" in q:
            language = "sql"
        elif "go " in q or "golang" in q:
            language = "go"
        
        # Script vs API mode detection
        simple_kw = ["hello world", "basit", "simple", "script", "yazdır", "yazdir", "print",
                     "fonksiyon", "function", "fibonacci", "faktöriyel", "ortalama", "çalıştır",
                     "standalone", "tek dosya", "component"]
        api_kw = ["api", "rest", "endpoint", "sunucu", "server", "backend", "fastapi", "flask",
                  "express", "django", "crud", "servis", "microservis"]
        
        mode = "script" if (any(kw in q for kw in simple_kw) and not any(kw in q for kw in api_kw)) else "api"
        framework = "script" if mode == "script" else "fastapi"
        if language == "javascript" and mode == "api":
            framework = "express"
        
        result = await self.tools.execute("generate_code", {
            "prompt": user_msg, "language": language,
            "framework": framework, "mode": mode
        })
        if result.get("success"):
            return self._llm_style(
                f"İşte istediğiniz kod ({language} • {mode.upper()} modu):\n\n"
                f"```{language}\n{result['code']}\n```\n\n"
                f"Bu kodu kopyalayıp doğrudan kullanabilirsiniz. Değişiklik veya yeni özellik ister misiniz?"
            )
        return self._llm_style(f"Kod oluşturulurken hata oluştu: {result.get('error', 'Bilinmeyen')}")
    
    async def _run_visual_tool(self, user_msg: str, q: str) -> Dict:
        """Build visual prompt params from natural language."""
        style = "cinematic"
        if any(kw in q for kw in ["anime", "manga"]): style = "anime"
        elif any(kw in q for kw in ["minimal", "sade"]): style = "minimalist"
        elif any(kw in q for kw in ["gerçekçi", "realistik", "foto", "photoreal"]): style = "photorealistic"
        elif any(kw in q for kw in ["concept", "konsept", "fantastik"]): style = "conceptual"
        
        result = await self.tools.execute("generate_visual_prompt", {
            "subject": user_msg,
            "environment": "cinematic lighting, atmospheric depth, detailed environment",
            "camera": "35mm lens, f/1.8, shallow depth of field, high detail",
            "style": style
        })
        if result.get("success"):
            return self._llm_style(
                f"Profesyonel görsel promptunuz hazır ({style} stil):\n\n"
                f"```\n{result['final_prompt']}\n```\n\n"
                f"Bu prompt'u Midjourney v6, Stable Diffusion XL veya DALL-E 3'te doğrudan kullanabilirsiniz. "
                f"Stil veya kompozisyon değişikliği ister misiniz?"
            )
        return self._llm_style(f"Görsel prompt oluşturulurken hata: {result.get('error', 'Bilinmeyen')}")
    
    async def _run_video_tool(self, user_msg: str, q: str) -> Dict:
        """Generate video prompt AND optionally create real video file."""
        video_model = "veo"
        if "sora" in q: video_model = "sora"
        elif "runway" in q: video_model = "runway"
        elif "luma" in q: video_model = "luma"

        # First generate the cinematic prompt
        result = await self.tools.execute("generate_video_prompt", {
            "timecode": "[00:00 - 00:05]",
            "camera_movement": "dynamic cinematic camera movement, smooth dolly motion",
            "motion_dynamics": user_msg,
            "video_model": video_model
        })

        if not result.get("success"):
            return self._llm_style(f"Video prompt oluşturulurken hata: {result.get('error', 'Bilinmeyen')}")

        # Check if user wants REAL video (not just prompt)
        wants_real_video = any(kw in q for kw in [
            "gerçek video", "real video", "video oluştur", "video üret",
            "video yap", "make video", "create video", "generate video",
            "video dosyası", "video file"
        ])

        if wants_real_video:
            # Generate actual video via backend
            try:
                import httpx
                async with httpx.AsyncClient(timeout=90.0) as client:
                    resp = await client.post(
                        f"{self.tools.backend_url}/api/v1/generate/real-video",
                        json={
                            "prompt": user_msg,
                            "duration": 5,
                            "width": 1280,
                            "height": 720
                        }
                    )
                    data = resp.json()

                if data.get("success"):
                    video_url = f"http://localhost:8000{data['video_url']}"
                    return self._llm_style(
                        f"🎬 **Gerçek video oluşturuldu!**\n\n"
                        f"📹 **Video:** [{data['video_id']}]({video_url})\n\n"
                        f"```html\n<video controls width=\"640\">\n  <source src=\"{video_url}\" type=\"video/mp4\">\n</video>\n```\n\n"
                        f"**Prompt:** {data['prompt'][:100]}...\n"
                        f"**Süre:** {data['duration']} saniye | "
                        f"**Çözünürlük:** {data['resolution']} | "
                        f"**Boyut:** {data['size_kb']} KB\n\n"
                        f"---\n\n"
                        f"**Sinematik Prompt (Veo/Sora için):**\n"
                        f"```\n{result['final_prompt']}\n```\n\n"
                        f"Videoyu indirmek için: [Videoyu İndir]({video_url})"
                    )
                else:
                    return self._llm_style(
                        f"⚠️ Video dosyası oluşturulamadı: {data.get('error', 'Bilinmeyen hata')}\n\n"
                        f"Ancak sinematik promptunuz hazır:\n\n"
                        f"```\n{result['final_prompt']}\n```\n\n"
                        f"Bu prompt'u Google Veo, OpenAI Sora veya Runway Gen-3'te kullanabilirsiniz."
                    )
            except Exception as e:
                return self._llm_style(
                    f"⚠️ Video oluşturma hatası: {str(e)}\n\n"
                    f"Sinematik promptunuz yine de hazır:\n\n"
                    f"```\n{result['final_prompt']}\n```\n\n"
                    f"Bu prompt'u harici video AI'larında kullanabilirsiniz."
                )
        else:
            # Just return the prompt (existing behavior)
            return self._llm_style(
                f"Sinematik video promptunuz hazır ({video_model} uyumlu):\n\n"
                f"```\n{result['final_prompt']}\n```\n\n"
                f"Bu prompt'u Google Veo, OpenAI Sora veya Runway Gen-3'te kullanabilirsiniz. "
                f"**Gerçek video dosyası** oluşturmamı ister misiniz? ('Video oluştur' yazın)"
            )
    
    async def _run_multi_tool(self, user_msg: str, q: str) -> Dict:
        """User wants multiple outputs - run tools in sequence."""
        sections = []
        tools_used = []
        
        if any(kw in q for kw in ["kod", "code", "api", "script", "python", "javascript"]):
            r = await self._run_code_tool(user_msg, q)
            sections.append(r["data"]["choices"][0]["message"]["content"])
            tools_used.append("generate_code")
        
        if any(kw in q for kw in ["görsel", "gorsel", "visual", "midjourney", "resim", "poster"]):
            r = await self._run_visual_tool(user_msg, q)
            sections.append(r["data"]["choices"][0]["message"]["content"])
            tools_used.append("generate_visual_prompt")
        
        if any(kw in q for kw in ["video", "film", "sahne", "sinematik"]):
            r = await self._run_video_tool(user_msg, q)
            sections.append(r["data"]["choices"][0]["message"]["content"])
            tools_used.append("generate_video_prompt")
        
        combined = f"**{len(sections)} çıktı oluşturdum:**\n\n" + "\n\n---\n\n".join(sections)
        return self._llm_style(combined)
    
    @staticmethod
    def _is_identity_query(query: str) -> bool:
        """Kimlik/model sorularını yakala (LLM/anahtar durumundan bağımsız)."""
        q = (query or "").casefold()
        phrases = (
            "hangi modelsin", "hangi model", "hangi llm", "modelin ne",
            "modelin adı", "modelin adi", "model ismi", "hangi yapay zeka",
            "sen nesin", "sen kimsin", "kimsin", "kendini tanıt",
            "kendini tanit", "adın ne", "adin ne", "ismin ne", "isminiz ne",
            "ne yapabilirsin", "neler yapabilirsin",
        )
        return any(p in q for p in phrases)

    @staticmethod
    def _local_server_reachable(url: str, timeout: float = 0.35) -> bool:
        """Kimlik yanıtında 'çalışıyor' demek için hızlı, güvenli port kontrolü."""
        try:
            parsed = urllib.parse.urlparse(url)
            host = (parsed.hostname or "").lower()
            if host not in {"127.0.0.1", "localhost", "::1"}:
                return False
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            return False

    def _identity_text(self) -> str:
        """Gerçek yapılandırmayı sızdırmadan açıklayan deterministik tanıtım."""
        try:
            self._refresh_llm_config()
        except Exception:
            pass
        model = (getattr(self.llm_config, "model", "") or "qwen2.5:3b").strip()
        provider = "local"
        local_model = (os.getenv("NEXUS_LOCAL_LLM_MODEL") or model).strip()
        local_url = (os.getenv("NEXUS_LOCAL_LLM_URL") or "http://127.0.0.1:11434/v1").strip()
        local_state = "çalışıyor" if self._local_server_reachable(local_url) else "bağlantı bekleniyor"

        return (
            "Ben **NEXUS-CORE v6.1** — çok modlu yerel bir yapay zeka ajanıyım. "
            "Tüm işlemlerinizi doğrudan bilgisayarınızda yerel Ollama motoru ile çalıştırırım.\n\n"
            "**Çalışma yapılandırmam:**\n"
            f"- 🎯 Yerel Sağlayıcı: Ollama (100% yerel, güvenli ve gizli)\n"
            f"- 💻 Aktif Model: `{model}` ({local_state})\n\n"
            "**Neler yapabilirim?**\n"
            "1. 💻 Kod üretimi, dosya düzenleme, komut çalıştırma ve test\n"
            "2. 🎨 Görsel prompt ve gerçek görsel üretimi\n"
            "3. 🎬 Sinematik video promptu ve MP4 üretimi\n"
            "4. 🌐 Web araması, soru-cevap ve öğrenme"
        )

    def _answer_question(self, query: str) -> str:
        """Rule-based question answering."""
        q = query.lower().strip()

        if self._is_identity_query(q):
            return self._identity_text()
        
        if any(kw in q for kw in ["merhaba", "selam", "hey", "naber", "nasılsın", "nasilsin"]):
            return ("Merhaba! Ben **NEXUS-CORE v6.1** yapay zeka ajanıyım. "
                    "Yerel Ollama motoru üzerinden çalışıyorum. Nasıl yardımcı olabilirim?")
        
        if "yapay zeka" in q and ("nedir" in q or "ne demek" in q):
            return ("**Yapay Zeka (AI)**, insan zekasını taklit eden sistemlerin genel adıdır. "
                    "Temel alt dalları:\n\n"
                    "- **Makine Öğrenmesi (ML)**: Verilerden öğrenen algoritmalar\n"
                    "- **Derin Öğrenme**: Sinir ağları ile karmaşık örüntü tanıma\n"
                    "- **Doğal Dil İşleme (NLP)**: İnsan dilini anlama ve üretme\n"
                    "- **Bilgisayarlı Görüntü**: Görselleri analiz etme\n\n"
                    "Bugün LLM'ler (Large Language Models) bu alanın en gelişmiş örneğidir.")
        
        if any(kw in q for kw in ["python nedir", "python ne"]):
            return ("**Python**, okunabilirliği yüksek, geniş kütüphane ekosistemine sahip "
                    "çok amaçlı bir programlama dilidir. Veri bilimi, yapay zeka, web "
                    "geliştirme (FastAPI, Django) ve otomasyon için yaygındır.")
        
        # Bilinmeyen sorularda kimliği koru; ham API hatası gösterme.
        return (
            "Ben **NEXUS-CORE v6.1** — yerel çalışan yapay zeka ajanıyım. "
            "Bu soru için yerel model şu anda yanıt üretemedi.\n\n"
            "Ollama servisinin açık olduğunu ve modelin yüklü olduğunu kontrol ederek "
            "yeniden deneyebilirsiniz."
        )


# ============================================================
# GLOBAL AGENT INSTANCE
# ============================================================

_agent_v6: Optional[NexusAIAgent] = None

def get_agent_v6(force_new: bool = False) -> NexusAIAgent:
    """Get or create global agent instance."""
    global _agent_v6
    if force_new or _agent_v6 is None:
        _agent_v6 = NexusAIAgent()
    return _agent_v6

def reset_agent_v6():
    """Force recreation of agent with fresh config."""
    global _agent_v6
    _agent_v6 = None
    return get_agent_v6()


async def chat(user_message: str, conversation_id: str = None, history=None, agent_id: str = None, tools_override: list = None, system_prefix: str = None, current_user = None) -> Dict:
    """Quick chat function."""
    agent = get_agent_v6()
    return await agent.chat(
        user_message, conversation_id, history=history, agent_id=agent_id,
        tools_override=tools_override, system_prefix=system_prefix,
        current_user=current_user,
    )


def get_agent_info(current_user = None) -> Dict:
    """Get agent information (yerel Ollama modeli)."""
    agent = get_agent_v6()
    try:
        agent._current_user = current_user
        agent._refresh_llm_config()
    except Exception:
        pass
    provider = "local"
    model = getattr(agent.llm_config, "model", "") or "qwen2.5:3b"
    return {
        "name": "NEXUS-CORE v6.1",
        "type": "True AI Agent",
        "capabilities": [
            "Question Answering",
            "Code Generation",
            "Visual Prompt Generation",
            "Video Prompt Generation",
            "Web Search",
            "Learning"
        ],
        "tools": [t["function"]["name"] for t in TOOLS],
        "llm_model": f"{provider}/{model}",
        "provider": provider,
        "model": model,
    }