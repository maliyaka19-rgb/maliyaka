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
