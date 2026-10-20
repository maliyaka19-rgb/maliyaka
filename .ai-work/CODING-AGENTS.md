# Kodlama Yöneticisi Ajanı Sistemi — Tam Rapor (MASTER PROMPT V3)

- Tarih: 2026-10-19 (Oturum 16)
- Geri dönüş noktası: git tag `pre-coding-agents` → `719cb7e`
- Commit: `f10e0ef` (main'e push edildi)
- Test durumu: **172 PASS** (önceki 150 korundu + 15 kodlama + 7 allow-list/eşzamanlılık)

---

## 1. Başlangıçtaki proje durumu

- Tek servis mimarisi: `backend/app.py` hem API, hem arayüz, hem Telegram'ı `:8000`'de sunar.
- Aktif model: **groq / openai/gpt-oss-20b** (gerçek, çalışıyor).
- 20 genel ajan (`custom_agents.py`), anahtar-kelime yönlendirmesi (`auto_select_agent`).
- "Ekip modu" (`/agents/team/run`) **sabit 3 çağrılık** pipeline'dı: uzman → denetçi → lider.
- Ajan şemasında hiyerarşi/category/kind yok; `max_iterations=25` ve `temperature=0.7` global.
- Araç allow-list'i yalnızca **reklam** düzeyinde etkiliydi; executor'da zorlama yoktu.

## 2. Tespit edilen ajanlar ve gerçek çalışma durumları

| Sınıf | Ajanlar | Not |
|-------|---------|-----|
| Çalışıyor ve test edilmiş | assistant, coder, python-pro, backend-pro, frontend-pro, reviewer, security, devops, chat-pro, analyst, designer, image-pro, video-pro, team-lead | gerçek LLM + araç döngüsü |
| Var, yeterince test edilmemiş | teacher, artist, researcher, writer, translator, marketer | persona + araç listesi var; uçtan uca test sınırlı |
| Tanımlı, mekaniği eksik | ekip modu orkestrasyonu | sabit pipeline; görev bölme/geri gönderme yok |
| Eksik | kod analiz, mimari, bağımlılık, hata düzeltme, veritabanı, entegrasyon, test, performans, debug, regresyon, dokümantasyon, optimizasyon, teknik araştırma, geri dönüş, kanıt denetimi, kod standardı, öğrenme, yöneticiler | bu oturumda eklendi |

## 3. Yeniden kullanılan / geliştirilen / eklenen uzmanlıklar

24 uzmanlık alanı eşlemesi (`custom_agents.py` içinde yorumla da belgelidir):

| # | Uzmanlık | Ajan | Durum |
|---|----------|------|-------|
| 1 | Kod Analiz | `code-analyst` | EKLENDİ |
| 2 | Sistem Mimarisi | `architect` | EKLENDİ |
| 3 | Görev Planlama | `coding-manager` | EKLENDİ (planlamayı kendisi yapar) |
| 4 | Bağımlılık/Ortam | `dependency-analyst` | EKLENDİ |
| 5 | Kod Geliştirme | `coder` / `python-pro` | YENİDEN KULLANILDI |
| 6 | Hata Düzeltme | `bug-fixer` | EKLENDİ |
| 7 | Backend/API | `backend-pro` | YENİDEN KULLANILDI |
| 8 | Frontend | `frontend-pro` | YENİDEN KULLANILDI |
| 9 | Veritabanı | `database-pro` | EKLENDİ |
| 10 | Entegrasyon | `integrator` | EKLENDİ |
| 11 | Test | `test-engineer` | EKLENDİ |
| 12 | Kod İnceleme | `reviewer` | YENİDEN KULLANILDI |
| 13 | Güvenlik | `security` | YENİDEN KULLANILDI |
| 14 | Performans | `performance-pro` | EKLENDİ |
| 15 | Hata Araştırma | `debugger` | EKLENDİ |
| 16 | Regresyon | `regression-tester` | EKLENDİ |
| 17 | DevOps/Dağıtım | `devops` | YENİDEN KULLANILDI |
| 18 | Dokümantasyon | `docs-writer` | EKLENDİ |
| 19 | Optimizasyon | `optimizer` | EKLENDİ |
| 20 | Öğrenme/Gelişim | `learning-agent` | EKLENDİ |
| 21 | Kod Standardı | `code-standards` | EKLENDİ |
| 22 | Teknik Araştırma | `tech-researcher` | EKLENDİ |
| 23 | Geri Dönüş | `rollback` | EKLENDİ |
| 24 | Kanıt Denetimi | `evidence-auditor` | EKLENDİ |
| + | Ana Yönetici | `main-manager` | EKLENDİ |

**Toplam ajan: 39** (mevcut 20 KORUNDU + 19 eklendi). Mevcut ajanlardan hiçbiri silinmedi,
hiçbirinin aracı/yönlendirmesi değiştirilmedi.

## 4. Değiştirilen ve oluşturulan dosyalar

| Dosya | İşlem | Özet |
|-------|-------|------|
| `backend/coding_manager.py` | YENİ | Orkestrasyon motoru (aşağıya bakın) |
| `backend/coding_routes.py` | YENİ | `/api/v1/coding/*` rotaları |
| `backend/custom_agents.py` | DEĞİŞTİ | 19 kodlama uzmanı + anahtar kelimeler |
| `backend/custom_agents.json` | DEĞİŞTİ | Yeni ajanların kalıcı kaydı (migration) |
| `backend/ai_agent.py` | DEĞİŞTİ | `tools_override`, `system_prefix`, `_tools_payload` düzeltmesi |
| `backend/app.py` | DEĞİŞTİ | coding router kaydı |
| `backend/tests/test_coding_manager.py` | YENİ | 15 gerçek test |
| `backend/tests/test_team_agents.py` | DEĞİŞTİ | "20" → ">=20 + orijinaller korunur" |
| `backend/tests/test_agents_specialization.py` | DEĞİŞTİ | Aynı gerekçe |
| `.gitignore` | DEĞİŞTİ | `coding_tasks.json` (çalışma-zamanı veri) |

## 5. Ana Yönetici Ajan entegrasyon durumu

Akış **gerçekten** kuruldu ve canlı test edildi:

```
KULLANICI → Ana Yönetici (intake/brief) → Kodlama Yöneticisi → uzmanlar
         → Kodlama Yöneticisi (rapor) → Ana Yönetici (inceleme) → KULLANICI
```

- Ana Yönetici (`main-manager`) görevi kabul eder (brief üretir) ve **sonuç raporunu inceler**.
- Kodlama Yöneticisi (`coding-manager`) Ana Yöneticiye bağlıdır; onun yerini almaz.
- Canlı testte Ana Yönetici, raporu inceleyip **kanıt eksikliğini** doğru bildirdi ve
  yapılmamış işi doğrulanmış saymadı.

## 6. Model ve araç bağlantılarının durumu

- Model: **groq / openai/gpt-oss-20b** — gerçekten çalışıyor (canlı test 200, gerçek yanıt).
- Ücretli API etkinleştirilmedi; mevcut bağlantı korundu.
- Araç allow-list artık adım bazında zorlanıyor (plan modunda yazma araçları verilmez).
- `run_verification` gerçek `subprocess` ile komut çalıştırır (kanıt).

## 7. Gerçek test sonuçları

**Birim/entegrasyon (pytest):** `python -m pytest tests/ -q --ignore=tests/test_api_live.py`

```
172 passed
```

Yeni `tests/test_coding_manager.py` (15 test):

| # | Test | Kapsam |
|---|------|--------|
| 1 | `test_classify_task_types` | 8 görev türü sınıflandırma |
| 2 | `test_all_workflow_roles_exist_as_agents` | her rol gerçek bir ajana karşılık geliyor |
| 3 | `test_workflows_cover_every_task_type` | her türün akışı var |
| 4 | `test_select_workflow_returns_defensive_copy` | mutasyon sızmıyor |
| 5 | `test_resolve_tools_least_privilege` | plan modunda yazma aracı YOK |
| 6 | `test_file_lock_registry_prevents_conflict` | dosya çakışması engelleniyor |
| 7 | `test_build_report_has_11_fields` | rapor 11 alan |
| 8 | `test_run_plan_mode_pipeline` | uçtan uca akış + rapor + kalıcılık |
| 9 | `test_execute_requires_confirmation` | onaysız execute → plan |
| 10 | `test_execute_with_confirmation_grants_write` | onaylı execute → yazma izni |
| 11 | `test_failed_verification_triggers_limited_retries` | başarısız test → 2 retry → düzelir |
| 12 | `test_agent_crash_is_recorded_not_lost` | ajan çökmesi sessizce kaybolmuyor |
| 13 | `test_parallel_analysis_runs_concurrently` | bağımsız analiz adımları paralel |
| 14 | `test_http_health_and_workflows` | HTTP health/workflows |
| 15 | `test_http_run_and_tasks` | HTTP run + tasks + 404 |

`tests/test_tool_allowlist.py` (7 test, yeni): executor izin verilmeyen aracı çalıştırmıyor
(`denied=True`, dosya oluşmuyor); izinli araç çalışıyor; `allowed=None` = kısıt yok;
`_allowed_tool_names` `_tools_payload` ile tutarlı; salt-okuma override yazmayı uçtan uca bloklar;
`_active_tools`/`_active_model` eşzamanlı görevlerde **izole** (contextvar).

**Canlı uçtan uca (gerçek LLM, plan modu):**
- `POST /api/v1/coding/run` → HTTP 200, ~116 sn
- adımlar: `code-analyst → coder → reviewer`, `status: tamamlandi`
- Ana Yönetici incelemesi: kanıt yokluğunu doğru bildirdi.

**Canlı kalite kapısı (gerçek komut):**
- `python -m pytest backend/tests/test_calculator.py -q` → exit 0, `32 passed`.

## 8. Başarısız ve çalıştırılamayan testler

- **Başarısız test yok.** 172/172 PASS.
- İlk canlı kalite kapısı denemesi `exit code 4 (no tests ran)` verdi: `run_verification`
  proje kökünde (`multimodal-studio`) çalışıyor, testler `backend/tests/` altında. Yol
  düzeltilince exit 0. Bu bir **bulgu ve düzeltme**dir; `working_dir` artık API'den
  ayarlanabilir.
- **NOT RUN / BLOCKED:** 7/24 bulut (Render) dağıtımı — kullanıcı hesabı gerekir.

## 9. Düzeltilen hatalar

1. **Güvenlik açığı:** `_tools_payload()` boş listeyi "tüm araçlar" sayıyordu; artık
   boş liste = hiç araç. Adım-bazlı en az yetki gerçekten uygulanıyor.
2. **Test hijyeni:** roster testleri "tam 20" iddiasından ">=20 + orijinaller korunur"
   iddiasına güncellendi (niyet korundu, sahte başarı yok).
3. **Çalışma-zamanı veri kirliliği:** `coding_tasks.json` gitignore'a eklendi; test
   artefaktları `tmp_path` kullanacak şekilde yazıldı.

## 10. Kalan sorunlar ve riskler

| Risk | Derece | Açıklama |
|------|--------|----------|
| Araç executor'da zorlama | ÇÖZÜLDÜ | `tool_executor.execute(allowed=…)` artık izin verilmeyen aracı ÇALIŞTIRMIYOR; `ai_agent._allowed_tool_names()` `_tools_payload` ile birebir tutarlı (5 yeni test). |
| Tek model sağlayıcı | ORTA (azaltıldı) | Yalnızca groq geçerli. **Devre kesici eklendi**: 401/403 alan sağlayıcı 30 dk atlanır (ölçüm: 22 istek/15.7 sn → **0 istek/0.00 sn**). Gerçek ikinci sağlayıcı için geçerli anahtar gerekir (BLOCKED). |
| LLM kanıtsız iddia | DÜŞÜK | Kalite kapısı + evidence-auditor + Ana Yönetici ile azaltıldı; tam garanti değil. |
| Uzun görev süresi | DÜŞÜK | 3 adım ~116 sn; TPM sınırı nedeniyle paralellik varsayılan KAPALI. |
| Eşzamanlı istekler | ÇÖZÜLDÜ | `_active_tools`/`_active_model` artık **contextvar** (istek-yerel); eşzamanlı sohbetler birbirinin iznini ezmez (2 test). |

## 11. Sonraki geliştirme adımları

1. `tool_executor.execute` içine allow-list zorlaması ekle (derinlemesine savunma) → **TAMAMLANDI** (commit `757af1e`).
2. İkinci model sağlayıcı/yerel model (LM Studio/Ollama) yedekliliği ekle → **TAMAMLANDI (yerel kısım)**; bulut ikinci sağlayıcı geçerli anahtar gerektirir (BLOCKED).
3. `_active_tools`/`_active_model`'i istek-yerel (contextvar) yap → **TAMAMLANDI** (commit `6bfacd7`).
4. Öğrenme Ajanı için geçmiş görev kayıtlarından otomatik içgörü üretimi (denetimli) → **TAMAMLANDI** (görev sonunda otomatik; `applied` daima `False`).
5. CI'da `test_coding_manager.py` + regresyonu zorunlu kapı yap.

---

## Ek: Mimari ve API

### `coding_manager.py` — gerçek orkestrasyon motoru

- `classify_task(message) -> TaskType` — 8 tür: feature, bugfix, security, performance,
  api, research, refactor, general (ağırlıklı anahtar kelime + öncelik sırası).
- `WORKFLOWS` — tür → uzman adımları (`role`, `goal`, `write`, `optional`).
- `CodingTaskManager.resolve_tools(agent, step, mode)` — adım-bazlı en az yetki.
- `FileLockRegistry` — aynı dosyayı iki ajanın eşzamanlı değiştirmesini engeller.
- `CodingTaskManager.run(...)` — Ana Yönetici intake → uzman adımları → (kalite kapısı +
  sınırlı retry) → rapor → Ana Yönetici incelemesi.
- `run_verification(command)` — gerçek komut çalıştırır; çıkış kodu = kanıt.
- `build_report(...)` — 11 alanlı yapılandırılmış rapor.
- Kalıcılık: `coding_tasks.json` (gitignore'lu, son 100 görev).

### `coding_routes.py` — API

| Yöntem | Yol | Açıklama |
|--------|-----|----------|
| GET | `/api/v1/coding/health` | rol hazırlığı + kayıtlı görev sayısı |
| GET | `/api/v1/coding/workflows` | tür → uzman akışları |
| POST | `/api/v1/coding/run` | görevi çalıştır (plan/execute) |
| GET | `/api/v1/coding/tasks` | görev kayıtları |
| GET | `/api/v1/coding/tasks/{id}` | tek görev detayı |

`POST /api/v1/coding/run` gövdesi:

```json
{
  "message": "…",
  "mode": "plan",
  "confirm": false,
  "via_main_manager": true,
  "verify_command": "python -m pytest backend/tests/test_x.py -q",
  "max_retries": 2,
  "parallel_analysis": false,
  "working_dir": null
}
```

### Görev durumları

`bekliyor`, `calisiyor`, `inceleme_bekliyor`, `test_basarisiz`, `tamamlandi`,
`basarisiz`, `onay_bekliyor`.

---

## Öğrenme katmanı (denetimli içgörü) — `coding_insights.py`

"Öğrenme ve Gelişim Uzmanı" (`learning-agent`) için **deterministik** öğrenme katmanı.
LLM/ag kullanmaz; aynı girdiden aynı çıktıyı üretir (test edilebilir).

### Girdi → Çıktı
- Girdi: `coding_tasks.json` (Kodlama Yöneticisi'nin kalıcı görev kayıtları).
- Çıktı: `coding_insights.json` (öneri listesi).

### Üretilen içgörü türleri
| kind | önem | koşul |
|---|---|---|
| `basarisizlik_orani` | risk | Bir görev türünde (n≥2) başarısızlık oranı ≥ %50 |
| `kanitsiz_tamamlama` | uyari | `tamamlandi` ama `verification.passed is not True` |
| `retry_yogunlugu` | bilgi | `retries > 0` olan görevler |
| `basarisiz_rol` | uyari | Aynı rol ≥2 görevde başarısız adım üretti |
| `tekrarlayan_kalan_risk` | uyari | Normalize edilmiş kalan risk ≥2 görevde tekrar etti |
| `veri_yok` | bilgi | Hiç görev kaydı yok |

### GÜVENLİK SINIRI (denetimli öğrenme)
- Modül **yalnızca** `coding_insights.json` yazar. Kaynak kod, `model_config.json`
  (model/anahtar) veya güvenlik kuralları **değiştirilmez**.
- Her içgörü `status="oneri"` başlar. `onaylandi` olsa bile `applied` **daima `False`**:
  onay otomatik uygulama değildir, yalnızca insan kararı kaydıdır.
- Test: `tests/test_coding_insights.py::test_module_writes_only_the_insights_file`
  yazılan tüm dosya yollarını sarar ve tek dosya kuralını doğrular.

### Rotalar (`/api/v1/coding`)
| Metot | Yol | Açıklama |
|---|---|---|
| GET | `/insights?status=` | İçgörüleri listeler (`oneri`/`onaylandi`/`reddedildi`) |
| POST | `/insights/analyze` | Geçmişi analiz eder, öneri üretir/kaydeder |
| POST | `/insights/{id}/approve` | `{"note": "..."}` — kararı kaydeder (uygulamaz) |
| POST | `/insights/{id}/reject` | `{"note": "..."}` — red kararını kaydeder |

### Kalıcılık politikası
- Her içgörü `kind + anahtar` için kararlı `imza` (sha1) taşır → tekrar analizde **çift
  kayıt olmaz**; kanıt/gerekçe tazelenir, **kimlik ve insan kararı korunur**.
- Kanıtı kalmayan kayıtlar yalnızca hâlâ `oneri` ise düşürülür; karar verilmiş kayıtlar
  **denetim izi** olarak saklanır.

### İlgili gerçek düzeltme
- `search_learning` aracı `/api/v1/learning/report` adresine POST atıyordu; endpoint
  yalnızca GET → canlı sunucuda **405**. GET'e çevrildi; artık gerçekten çalışıyor
  (canlı kanıt: `success=True`, rapor uzunluğu 1051).

## Ek 9 - Execute modu gercek kanit (izole proje)
- Uctan uca `mode=execute`: gercek `write_file`/`edit_file` + gercek `pytest` (exit=0).
- Rapor artik **gercek** degisen dosyalari listeler (arac sonucundan).
- "Yazma adimi basarili ama 0 dosya" -> `kalan_riskler` uyarisi (canlida `coder` boyleydi).
- Dogrulama gecerken LLM 429 verse bile `final_answer` kanittan uretilir.
- Kalan kalite riski: ajanin urettigi kodda olu satir kalabiliyor; reviewer kacirdi.

## Ek 10 - working_dir gorev-yerel (ContextVar)
- Ajan araclari artik gorevin dizininde yazar/calisir; eszamanli gorevler izole.
- Canli API kaniti: dosya gorev dizininde, ana repo temiz, bagimsiz pytest exit=0.
- **ACIK KRITIK RISK**: `/api/v1/coding/*` kimlik dogrulamasi yok; internete acmadan once kapat.

## Ek 11 - 20 uzmanli kadro ve hiyerarsi
- **Tek kaynak**: `custom_agents.CODING_SPECIALISTS` (20; 4/6/5/5). `task-planner` eklendi.
  `coding_hierarchy()` eksik ajanı `missing` alanında açıkça bildirir.
- **API**: `GET /api/v1/agents/hierarchy` (Ana Yönetici + Kodlama Yöneticisi + gruplar).
- **Gerçek görev bağı**: FRONTEND/DATABASE/DEVOPS görev türleri + akışları; FEATURE/API/BUGFIX'e
  planner ve bağımlılık/danışma adımları. `learning-agent` görev sonu içgörüleri üretir
  (`agent` alanı), `applied=false`.
- **Arayüz**: Ajan penceresi hiyerarşik: Yönetim -> Kodlama Yöneticisi · 20 uzman -> A/B/C/D ->
  Diğer Ajanlar. `sohbet.html` `app.js?v=70`.
- **Kanıt**: 244 PASS; canlı `plan` 71.1 sn, `task_type=frontend`, zincir
  code-analyst -> frontend-pro -> test-engineer -> reviewer -> regression-tester; nihai yanıt
  Ana Yönetici'den.

## Ek 12 - Otomatik seçim = yalnızca Ana Yönetici
- `auto_select_agent()` daima `main-manager`; anahtar kelime mantığı `keyword_select_agent()`
  olarak korunur (ekip modu kullanır).
- `/api/v1/ai/chat`: otomatik + kodlama görevi → `CodingTaskManager.run(plan,
  via_main_manager=True)`; genel sohbet tek ajan.
- Sohbetten yazma yok (plan); uygulama için Kodlama Ekibi/execute.
- Kanıt: **249 PASS**; canlı genel mesaj 1 sn (zincir yok), kodlama mesajı 79.1 sn
  (frontend zinciri, nihai yanıt Ana Yönetici'den).

## Ek 13 - Resmî 22 ajanlık kadro (yalnızca istenen ajanlar)
- **Kadro**: `main-manager` (Ana Yönetici Ajan) + `coding-manager` (Kodlama Yönetici Ajanı)
  + `CODING_SPECIALISTS` (20). Toplam **22**.
- **Kaldırılan 18 ajan**: assistant, teacher, designer, analyst, artist, researcher, writer,
  translator, marketer, chat-pro, python-pro, image-pro, video-pro, team-lead,
  tech-researcher, rollback, evidence-auditor, code-standards.
- **Tek kaynak**: `OFFICIAL_AGENT_IDS`, `OFFICIAL_AGENT_NAMES`; `DEFAULT_AGENTS` ve
  `load_agents()` yalnızca bunları döndürür. Eski JSON'daki kaldırılmış kayıtlar yüklenmez.
  18 eski ajanın kaynak tanım blokları da AST ile silindi (1.565 -> 995 satır).
- **İş akışı**: `evidence-auditor` → `reviewer`; `tech-researcher` → `architect`;
  `team/run` lideri → `main-manager`.
- **Arayüz**: 22 kart; Yönetim + 20 uzman (4/6/5/5); eski `assistant` seçimi
  `main-manager`'a taşınır. `sohbet.html` `app.js?v=73`.
- **Kanıt**: 251 PASS; ruff temiz; `/api/v1/agents` 22; `/api/v1/agents/hierarchy`
  `total_specialists=20`, `missing=[]`; gerçek tarayıcı DOM'unda 22 kart ve 4/6/5/5.
