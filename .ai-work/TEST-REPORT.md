# T-008 API Entegrasyon Test Raporu

Tarih: 2026-10-16 23:52

Ozet: **34/36 PASS**

| Sinif | Method | Endpoint | Status |
|---|---|---|---|
| PASS | POST | `/api/v1/auth/login` | 200 |
| PASS | GET | `/` | 200 |
| PASS | GET | `/health` | 200 |
| PASS | GET | `/api/v1/models/catalog` | 200 |
| PASS | GET | `/api/v1/models/providers` | 200 |
| PASS | GET | `/api/v1/models/active` | 200 |
| PASS | GET | `/api/v1/agents` | 200 |
| PASS | GET | `/api/v1/agents/tools/available` | 200 |
| PASS | GET | `/api/v1/ai/info` | 200 |
| PASS | GET | `/api/v1/ai/conversations` | 200 |
| PASS | GET | `/api/v1/ai/learning/stats` | 200 |
| PASS | GET | `/api/v1/agent/status` | 200 |
| PASS | GET | `/api/v1/agent/tools` | 200 |
| PASS | GET | `/api/v1/agent/sessions` | 200 |
| PASS | GET | `/api/v1/agent/memory/stats` | 200 |
| PASS | GET | `/api/v1/brain/stats` | 200 |
| PASS | GET | `/api/v1/brain/skills` | 200 |
| PASS | GET | `/api/v1/brain/lessons` | 200 |
| PARTIAL | GET | `/api/v1/brain/context` | 422 |
| PASS | GET | `/api/v1/brain/experiences` | 200 |
| PASS | GET | `/api/v1/brain/reflections` | 200 |
| PARTIAL | GET | `/api/v1/brain/predict` | 422 |
| PASS | GET | `/api/v1/fs/drives` | 200 |
| PASS | GET | `/api/v1/fs/home` | 200 |
| PASS | GET | `/api/v1/fs/desktop` | 200 |
| PASS | GET | `/api/v1/fs/browse` | 200 |
| PASS | GET | `/api/v1/fs/current-project` | 200 |
| PASS | GET | `/api/v1/fs/recent-projects` | 200 |
| PASS | GET | `/api/v1/project/stats` | 200 |
| PASS | GET | `/api/v1/project/tree` | 200 |
| PASS | GET | `/api/v1/learning/report` | 200 |
| PASS | GET | `/api/v1/learning/summary` | 200 |
| PASS | GET | `/api/v1/auth/me` | 200 |
| PASS | GET | `/api/v1/auth/chats` | 200 |
| PASS | POST | `/api/v1/generate/visual` | 200 |
| PASS | POST | `/api/v1/ai/chat` | 200 |

---

## Ek — Oturum 7 Testleri (2026-10-17)

### Otomatik test paketi
| Grup | Adet | Komut | Sonuç |
|------|------|-------|-------|
| Birim (canlı hariç) | 82 | `python -m pytest tests/ -q` | ✅ PASS |
| Canlı API | 29 | `python -m pytest tests/test_api_live.py -m live` | ✅ PASS |
| **Toplam** | **111** | | **✅ 0 FAIL** |

### Yeni regresyon testleri — `tests/test_response_validation.py` (8)
| Test | Amaç | Sonuç |
|------|------|-------|
| `test_validate_plain_content_response` | normal içerik yanıtı geçerli | ✅ |
| `test_validate_tool_call_without_content` | **araç çağrısı, content yok → geçerli** (Groq regresyonu) | ✅ |
| `test_validate_tool_call_with_content` | content=null + tool_calls geçerli | ✅ |
| `test_validate_rejects_empty_message` | ne content ne tool_calls → geçersiz | ✅ |
| `test_validate_rejects_non_assistant_role` | role≠assistant → geçersiz | ✅ |
| `test_validate_rejects_bad_tool_call_type` | tool_call type≠function → geçersiz | ✅ |
| `test_validate_rejects_missing_choices` | choices yok → geçersiz | ✅ |
| `test_user_message_sent_once_to_llm` | kullanıcı mesajı LLM'e **1 kez** gider | ✅ |

### Statik analiz / lint
- `ruff check --select=E9,F63,F7,F82 .` → **All checks passed!** (önce 8× `F821`).
- `node --check js/app.js` → OK.
- `python -c "import web_tools, tools_spec, memory, tool_executor, rag_system, ai_agent, app"` → OK.

### F821 düzeltme doğrulaması (doğrudan)
| Kontrol | Sonuç |
|---------|-------|
| `tool_executor.CALCULATOR.evaluate("12 * 8")` | ✅ `{'success': True, 'result': 96, ...}` |
| `app._javascript_express_template(...)` | ✅ üretildi |
| `app._typescript_nextjs_template(...)` | ✅ üretildi |
| `from auth import save_users` | ✅ |
| `agent_routes.deque` | ✅ |
| `web_tools.os` | ✅ |

### R8 — Video üretimi (manuel, T-016)
| Adım | Sonuç |
|------|-------|
| `POST /api/v1/generate/real-video` | ✅ 200 (40.9 sn) |
| Üretilen dosya | ✅ `vid_*.mp4`, 37.752 bayt, geçerli `ftyp` imzası |
| `GET /api/v1/videos/{id}` | ✅ 200 `video/mp4` |

### CORS (G2) canlı doğrulama
- `GET /health` (`Origin: http://localhost:8080`) → `Access-Control-Allow-Origin: http://localhost:8080` ✅
  (wildcard yerine açık allowlist).

---

## Ek — Oturum 8 Testleri: 429 dayanıklılığı (2026-10-17)

### Otomatik test paketi
| Grup | Adet | Komut | Sonuç |
|------|------|-------|-------|
| Birim (canlı hariç) | **92** | `python -m pytest tests/ -q` | ✅ PASS |
| Canlı API (`live`) | 29 | `python -m pytest tests/test_api_live.py -m live` | ✅ PASS |
| **Toplam** | **121** | | **✅ 0 FAIL** |

> Not: birim sayısı 82 → 92 (10 yeni 429-regresyon testi). Canlı 29 test bu oturumda yeniden
> çalıştırılmadı (deselected); önceki Oturum 7 sonucu geçerli.

### Yeni regresyon testleri — `tests/test_rate_limit_retry.py` (10)
| Test | Amaç | Sonuç |
|------|------|-------|
| `test_parse_retry_after_header` | `Retry-After` başlığı okunur | ✅ |
| `test_parse_retry_after_body_seconds` | "try again in 7.5s" okunur | ✅ |
| `test_parse_retry_after_body_minutes` | "in 1m30s" → ~90sn | ✅ |
| `test_parse_retry_after_default_when_unparseable` | ayrıştırılamazsa varsayılan | ✅ |
| `test_parse_retry_after_header_is_capped` | 9999 → tavan 90 | ✅ |
| `test_call_llm_retries_429_then_succeeds` | 2×429 → retry → başarı | ✅ |
| `test_call_llm_exhausted_429_marks_fallback_rate_limited` | tükenince `rate_limited=True` | ✅ |
| `test_call_llm_uses_retry_budget` | deneme = `MAX_RETRIES+1` | ✅ |
| `test_fallback_keeps_rate_limited_provider` | 429'da sağlayıcı **korunur**, kardeş model denenir | ✅ |
| `test_fallback_drops_provider_on_hard_failure` | sert hatada sağlayıcı **elenir** | ✅ |

### Canlı uçtan-uca doğrulama (gerçek Groq + gerçek HTTP)
| Adım | Sonuç |
|------|-------|
| `POST /api/v1/auth/login` | ✅ 200 |
| `POST /api/v1/fs/open-project` (geçici dizin) | ✅ 200 |
| `POST /api/v1/ai/chat` ("…yemek blog… 3 dosya oluştur") | ✅ 200 (**77 sn**) |
| `tools_used` | ✅ `['write_file','write_file','write_file']` |
| Yanıt | ✅ anlamlı özet — **"tam yanıt üretemiyorum" YOK** |
| Üretilen dosyalar | ✅ `app.py` (1898 B), `index.html` (867 B), `style.css` (655 B) |

**Sunucu log kanıtı (retry devrede):**
```
429 → Rate limited (429) on groq/openai/gpt-oss-120b; waiting 26.0s before retry 1/3
200 (retry başarılı)
429 → waiting 33.0s before retry 1/3   (yeni iterasyon)
429 → waiting 2.0s before retry 2/3    (aynı çağrı, 2. deneme)
200 (retry başarılı)
```

### Statik analiz
- `python -m py_compile ai_agent.py` → OK
- `ruff check --select=E9,F63,F7,F82 ai_agent.py` → **All checks passed!**

### SINIFLANDIRMA
- **Birim 429-retry**: **PASS**
- **Canlı çok adımlı görev (eski FAIL senaryosu)**: **PASS**
- **Regresyon**: **PASS** (mevcut 82 + yeni 10)

---

## Oturum 9 — Sohbet görsel render (frontend)

### Yöntem
- Gerçek `http://localhost:8080/sohbet.html` (Chromium sekmesi) yüklendi.
- `/api/v1/ai/chat` yanıtı, gönderim akışı bozulmadan fetch-intercept ile taklit edildi;
  böylece gerçek `md()` + CSS + görsel proxy + tarayıcı yüklemesi uçtan uca test edildi.

| Kontrol | Sonuç |
|---------|-------|
| Markdown görseli (`![]()`) gerçek `<img>` olarak render | ✅ |
| Görsel proxy üzerinden yüklendi | ✅ 768×768, ~2.5 sn |
| `loaded` sınıfı + iskelet gizleme + `opacity: 1` | ✅ |
| Ekran görüntüsü (görsel görünür) | ✅ |
| Çıplak pollinations URL → görsel | ✅ |
| Kod bloğu içindeki URL görsele dönüşmez | ✅ (`preHasFigure: 0`) |
| Çoklu görsel (2 markdown + 1 çıplak) | ✅ (3 figür) |
| Literal `![` metni kalmıyor | ✅ |
| `node --check js/app.js` | ✅ |

### Önceki (kırık) davranış kanıtı
- `img.complete=false`, `naturalWidth=0`, `currentSrc=""`, 75 sn boyunca **hiç ağ isteği yok**
  (`loading="lazy"` + yükseklik 0). `loading="eager"` ile aynı URL **2.3 sn'de** yüklendi.

### SINIFLANDIRMA
- **Markdown görsel render**: **PASS**
- **Proxy üzerinden yükleme**: **PASS**
- **Kenar durumları**: **PASS**
- **Regresyon (backend testleri etkilenmedi)**: **PASS**
