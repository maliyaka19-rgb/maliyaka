# NEXUS-CORE v6.1 — Karar Kaydı (DECISIONS.md)

> MASTER PROMPT V3 §6 gereği. Her önemli teknik karar; bağlam, karar, gerekçe,
> alternatifler ve etki ile birlikte kaydedilir.

---

## D-001 — Sürüm kontrolü: Git kurulumu (zip yedeği yerine)
- **Tarih**: 2026-10-17
- **Karar**: `winget` ile Git v2.55.0.5 kuruldu; repo `C:\Users\HP\Desktop\YAPAY ZEKA`
  altında `git init -b main` ile başlatıldı.
- **Gerekçe**: §3.9 & §11 geri alınabilirlik ister; başlangıçta Git yoktu (zip geçici ikame).
- **Alternatif**: Yalnızca zip snapshot (ilk fazda kullanıldı: `.backup/…zip`).
- **Etki**: Gerçek sürüm kontrolü; sırlar/kullanıcı verisi `.gitignore` ile hariç.

## D-002 — Sır yönetimi: `.gitignore` beyaz listesi
- **Karar**: `.env`, `.env.local`, `.encryption_key`, `model_config.json`, `auth_data/`,
  `brain_data/`, `learning_registry/`, `recent_projects.json`, `generated_videos/`,
  `chroma_db/`, `.next/`, `node_modules/`, `.backup/` **commit edilmez**.
- **Gerekçe**: §11 — anahtarları koda gömmeme / loglara-raporlara sızdırmama; kullanıcı gizliliği.
- **Etki**: Commit öncesi içerik sır taraması temiz; 61 kaynak/doküman dosyası commitlendi.

## D-003 — RAG ağır bağımlılıkları: guarded + LAZY import
- **Karar**: `chromadb` ve `sentence_transformers` modül yüklenirken değil, ilk kullanımda
  (`get_chroma_client`/`get_embedding_model`) yüklenir; varlık `importlib.util.find_spec` ile
  ucuzca kontrol edilir. Import anındaki `get_collection()` çağrısı kaldırıldı.
- **Gerekçe**: §12 performans — `import ai_agent` **28.7s → 0.89s**.
- **Alternatif**: Modül seviyesinde guarded import (ilk faz) → her başlangıçta ~28s.
- **Etki**: RAG işlevsel kaldı (canlı doğrulandı); ilk RAG çağrısı tek seferlik ~25s model yüklemesi yapar.

## D-004 — Test kimlik bilgileri ortamdan (env) okunur
- **Karar**: Canlı API testleri `NEXUS_TEST_EMAIL`/`NEXUS_TEST_PASSWORD` env değişkenlerinden
  beslenir; koda/rapora gömülmez. Varsayılan çalıştırmada `live` marker'ı hariç tutulur.
- **Gerekçe**: §11 & §14 — gerçek entegrasyon testini mock'tan ayır, sır sızdırma.

## D-005 — CORS: wildcard yerine açık allowlist (G2)
- **Karar**: `allow_origins=["*"]` kaldırıldı; `CORS_ORIGINS` env değeri + güvenli yerel
  varsayılanlar (8080/8000/3000) birleşimi kullanılır. `*` girdisi yok sayılır.
- **Gerekçe**: §11 — `*` + `allow_credentials=True` hem geçersiz hem güvensiz.
- **Etki**: Arayüz (8080) sorunsuz çalışır; üretimde env ile daraltılır.

## D-006 — Video: sahte sistem kurma, mevcut ücretsiz yolu doğrula
- **Karar**: Gerçek video modeli (Veo/Sora/Runway) **entegre edilmedi** (hesapta API yok).
  Mevcut ücretsiz yol (Pollinations kareleri + moviepy → mp4) korunup **gerçek çıktıyla**
  doğrulandı. `/generate/video` (metin-only) ile `/generate/real-video` (mp4) ayrımı belgelendi.
- **Gerekçe**: §10 — "kullanılabilir video API/modeli yoksa sahte üretim sistemi kurma;
  önce sağlayıcı arayüzünü hazırla, eksik bağlantıyı açıkça raporla."

## D-007 — Eksik bağımlılıklar açıkça bildirilir ve eklenir
- **Karar**: `requirements.txt`'e `cryptography`, `numpy`, `Pillow`, `moviepy` eklendi.
- **Gerekçe**: `model_routes.py` Fernet (`cryptography`) kullanır; `video_generator.py`
  `numpy`/`PIL`'i modül üstünde import eder → eksikse uygulama **başlamaz**. RAG paketleri
  (`chromadb`, `sentence-transformers`) ise **opsiyonel** (lazy/guarded) olarak belgelendi.
- **Etki**: Temiz kurulumda (`pip install -r requirements.txt`) uygulama ayağa kalkar.

## D-008 — Arayüz: gerçek çıktı, sahte ilerleme yok
- **Karar**: Live-status ilerleme çubuğu sahte yüzdeden **belirsiz (indeterminate)** animasyona
  çevrildi; görsel proxy çağrısı mutlak backend URL'ine (`http://localhost:8000`) düzeltildi;
  Pollinations `402` için sunucu tarafında sınırlı retry/backoff eklendi.
- **Gerekçe**: §13 — "sırf animasyon için sahte ilerleme/başarı üretme" ve gerçek görsel gösterimi.

## D-009 — Gerçek uzman görev aktarımı (alt ajanlar)
- **Karar**: Bağımsız denetimler OpenCode alt ajanlarına (`explore`) devredildi:
  video altyapı denetimi ve frontend entegrasyon denetimi.
- **Gerekçe**: §4 & §16 — "en az bir gerçek uzman görev aktarımı doğrulanmalı".
- **Etki**: İki bağımsız ajan raporu dosya:satır kanıtlarıyla alındı; bulgular düzeltmelere dönüştü.

## D-010 — 429 (rate limit): bekle & aynı sağlayıcıyı yeniden dene; sağlayıcıyı düşürme
- **Tarih**: 2026-10-17
- **Bağlam**: Çok adımlı görevlerde (birden çok `write_file`) Groq **TPM 8000** limiti dolunca
  429 alınıyor; eski kod her hatada fallback zincirine düşüp **tek geçerli sağlayıcıyı (groq)
  eliyordu** → görev "Üzgünüm, tam yanıt üretemiyorum" ile bitiyordu.
- **Karar**:
  1. `_call_llm` bir 429'da **bekler** (`Retry-After` / "try again in Xs" ayrıştırılır) ve **aynı
     provider/model'i** `_RATE_LIMIT_MAX_RETRIES = 3` kez yeniden dener.
  2. `_fallback_chain`, `rate_limited=True` iken **sağlayıcıyı düşürmez**; aksine başa alıp diğer
     modellerini dener (ayrı TPM kovaları). Yalnızca **sert** hata (401/404/validasyon) sağlayıcıyı eler.
  3. Son araçsız çağrıya da retry; `max_iterations` 10→15.
- **Gerekçe**: §12 — kota hatalarını izle, gereksiz çağrıyı azalt; §3.9 — gerçek/geri alınabilir.
  429 **geçicidir**; doğru tepki bekleyip yeniden denemektir, sağlayıcıyı elden çıkarmak değil.
- **Alternatif**: Sistem prompt'unu küçültmek (TPM'i düşürür) — ek ajan yeteneği kaybı riski;
  ileride ek olarak değerlendirilebilir.
- **Etki**: Canlı doğrulandı — 3 dosyalı çok adımlı görev artık **hatasız** tamamlanıyor;
  10 yeni regresyon testi.

## D-011 — Ajan yeteneği: araç allow-list'i zorunlu kıl + tamamlama protokolü
- **Tarih**: 2026-10-17
- **Bağlam**: Ajanların `tools` alanı yalnızca metadata'ydı; LLM'e **her zaman 20 aracın tamamı**
  bildiriliyordu. Ayrıca prompt'lar görevi "tarif edip bırakma"ya izin veriyordu → zayıf/yarım görevler.
- **Karar**: `_tools_payload()` aktif ajanın allow-list'ini **uygular**; paylaşılan ajan son-ekine
  ve ana prompt'a "PLANLA → TAMAMEN YÜRÜT → DOĞRULA → RAPORLA" protokolü eklendi; `max_iterations`
  15→25; araç hatasında düzeltici sistem notu; `answer_question` uygulandı.
- **Gerekçe**: §3.2 "görevi bitir, yarım bırakma"; allow-list hem doğru yetkiyi hem küçük istek boyutunu sağlar.
- **Etki**: CANLI — `coder` 3 dosyalı görevi 77 sn'de tamamladı (`write_file`×3 + `list_files` doğrulama).

## D-012 — İstek penceresi: `_safe_window` ile 413 (TPM) koruması
- **Bağlam**: Uzun çok adımlı görevde biriken araç çıktıları Groq ücretsiz **TPM 8000**'i aştı →
  HTTP 413 → fallback zinciri tükendi → kural-tabanlı "Üzgünüm..." yanıtı. (Araç dizisi tek başına ~2.8k token.)
- **Karar**: `_call_llm`, mesajları `_safe_window()` ile budar: system + son ~20 mesaj; budama daima
  bir `user` (veya tool_calls'sız assistant) sınırında başlar → **yetim `tool` mesajı üretilmez**;
  ek olarak 28k karakter tavanı.
- **Alternatif**: Geçmişi tamamen kırpmak (bağlam kaybı) veya prompt'u küçültmek (yetenek kaybı) — reddedildi.
- **Etki**: +3 test; canlı görev 413 olmadan tamamlandı.

## D-013 — Telegram: ham Bot API + uzun yoklama, sır şifreli
- **Bağlam**: Kullanıcı Telegram'dan kontrol + sohbet istedi; hesapta ağır bağımlılık yok.
- **Karar**: Yeni kütüphane eklemek yerine mevcut `httpx` ile **ham Telegram Bot API** + uzun yoklama
  (`getUpdates`); token `model_routes._encrypt_key` (Fernet) ile **şifreli** saklanır ve API asla
  token'ı döndürmez (`token_set` boolean). `telegram_config.json` `.gitignore`'a eklendi.
- **Gerekçe**: §7/§10 — gereksiz bağımlılık ve sahte sistem kurma; §11 — sır sızdırma yok.
- **Etki**: 19 hermetic test PASS; uçlar canlı doğrulandı. Gerçek bot için kullanıcı token'ı gerekir.

## D-014 — Arayüz: light mode varsayılan + 3 sütun, mevcut JS'i koruyarak
- **Bağlam**: Kullanıcı light/modern bir arayüz istedi; mevcut `js/app.js` 100KB+ ve işlevsel.
- **Karar**: Sıfırdan Tailwind yeniden yazımı yerine **CSS değişkenlerini** light'a çevir +
  `[data-theme="dark"]` ile koyuyu koru; eksik işlevleri (proje/dosya işlemleri, ajan modali,
  mobil menü) ekle. İşlevselliği bozmadan modernize et.
- **Gerekçe**: §3.9 — geri alınabilir, düşük riskli; çalışan 103KB JS'i atmamak.
- **Etki**: Tarayıcıda 0 konsol hatası; tema geçişi, proje akışı ve ajan modali doğrulandı.


## D-015 - Ajan ekip akisi: asama basina AYRI konusma kimligi
- **Baglam**: `/agents/team/run` uc asamayi (uzman/denetci/lider) tek `conversation_id` ile
  cagiriyordu; sonuc `response` icine ara talimatlar ve onceki baglam sizip nihai cikti kirlendi.
- **Karar**: Her asama ayri kimlikte calisir (`<taban>-d`, `-r`, `-f`) ve promptlar
  "talimati/raporu TEKRAR ETME, sadece nihai teslimati yaz" der. Donen `conversation_id` taban kalir.
- **Gerekce**: 2.1 - kalite; 9.4 - sizinti yok.
- **Etki**: Canli ekip yaniti temiz; test_team_agents 5/5 PASS.

## D-016 - 400 "tool call validation failed" icin araclari kapatan tekrar deneme
- **Baglam**: groq/gpt-oss bazi turlarda ilan edilmeyen bir araci (`write_file`) cagiriyor; saglayici
  400 donuyor; eski davranis 20+ saglayicilik fallback zincirini tetikleyip isi yavaxlatiyor ve
  sik sik kural tabanli yanita dusuruyordu.
- **Karar**: Bu ozel 400'de AYNI modeli `tools`/`tool_choice` olmadan BIR kez daha dene; basarisizsa
  normal fallback'e devam et. Ilgisiz 400'ler etkilenmez.
- **Gerekce**: 4.1 - minimum mudahale; 6 - hiz; 1.1 - gercek duzeltme.
- **Etki**: `tests/test_tool_mismatch.py` 3 PASS (basari, basarisizsa fallback, ilgisiz 400).

## D-017 - API tabani yapilandirilabilir (config.js)
- **Baglam**: Arayuzde `http://localhost:8000` sabit kodluydu; hosting'de calismaz.
- **Karar**: `API_BASE = window.NEXUS_API_BASE || <ayni-host>:8000`; `config.js` ile override.
  Yerelde hicbir ayar gerekmez. Ayni yaklasim `chat.html` ve `telegram.html` icin de uygulandi.
- **Gerekce**: 7 - dagitilabilirlik; 8 - en az degisiklikle.
- **Etki**: Tarayicida 0 hata; localhost varsayilani korundu.

## D-018 - Masaustu uygulama: Electron + bagimliliksiz statik sunucu
- **Baglam**: Kullanici masaustu uygulamasi istedi (Electron/Tauri).
- **Karar**: Electron secildi (Node zaten var). Arayuz `file://` yerine kucuk bir yerel HTTP
  sunucusundan servis edilir (localStorage/CORS/goreli yol sorunlari olmasin). Python backend
  port 8000 doluysa dokunulmaz, degilse baslatilir. Statik sunucu ayri dosyaya cikarilip
  Electron'suz test edilir.
- **Gerekce**: 10 - sifirdan dev yeniden yazim yok; test edilebilirlik.
- **Etki**: Statik sunucu 6/6 PASS; Electron gercekten acildi (pencere "NEXUS-CORE", :8090).
  Paketlemede Windows sembolik link kisiti asildi (winCodeSign arsivi darwin haric cikarildi).

## D-019 - CORS: geri dongu (loopback) origin'leri porttan bagimsiz izinli
- **Baglam**: Masaustu (Electron) uygulamasi arayuzu 127.0.0.1:8090'dan servis eder;
  bu origin izin listesinde olmadigi icin tarayici TUM API cagrilarini blokladi
  ("Failed to fetch"). Uygulama hicbir veri yukleyemiyordu.
- **Karar**: `allow_origin_regex` ile yalnizca geri dongu adreslerine
  (`http://(localhost|127.0.0.1)(:\d+)?`) porttan bagimsiz izin ver; ayrica 8090
  acikca eklendi. Dis origin'ler reddedilmeye devam eder; joker "*" KULLANILMADI.
- **Gerekce**: 1.1 - gercek duzeltme; 9.4 - guvenlik (yalnizca kullanici makinesi);
  masaustu uygulamasi 8090 doluysa rastgele port secebildigi icin regex sart.
- **Etki**: Paketli uygulamadan gercek LLM yaniti alindi (DESKTOP_OK, 0 konsol hatasi);
  yeni `tests/test_cors.py` 5/5 PASS. `render.yaml` icindeki yanlis ortam degiskeni
  adi (`CORS_ALLOW_ORIGINS` -> `CORS_ORIGINS`) da duzeltildi.

## D-020 - Tek servis mimarisi + `API_BASE` otomatik algilama duzeltmesi
- **Baglam**: Ucretsiz genel yayin (tunel/hosting) icin tek adres gerekiyordu. Eski
  `API_BASE` kurali her zaman `<ayni-host>:8000` uretiyordu; `https://xxx.trycloudflare.com`
  adresinde bu `https://xxx.trycloudflare.com:8000` gibi GECERSIZ bir adrese donusuyor ve
  istek sessizce basarisiz oluyordu (misafir girisi calismiyordu).
- **Karar**: (a) Backend arayuzu de servis eder: `app.py` sonunda
  `app.mount("/", StaticFiles(directory=UI_DIR, html=True))` (mount EN SONDA; API rotalari
  onceligini korur). (b) `API_BASE` sirasi: `window.NEXUS_API_BASE` -> sayfa 8080/8090
  portundan geliyorsa `<ayni-host>:8000` -> **aksi halde `location.origin` (ayni origin)**.
- **Gerekce**: 7 - dagitilabilirlik; 1.1 - gercek duzeltme; 6.3 - CORS/config gerektirmez.
- **Etki**: Yerel `localhost:8000/sohbet.html` calisiyor; genel tunel adresinde misafir
  girisi + gercek LLM sohbeti 0 konsol hatasiyla dogrulandi; 138 backend testi PASS;
  yerel 8080 ve masaustu 8090 davranisi bozulmadi. `tunnel.ps1` ile hesapsiz yayin.

## D-021 - Log gizliligi: bot token'i loglara siziyordu (SecretRedactingFilter)
- **Baglam**: Telegram botu baglanip uzun yoklamaya (long polling) basladiginda uygulama
  logunda su satir goruldu:
  `httpx - INFO - HTTP Request: GET https://api.telegram.org/bot<ID>:<TOKEN>/getMe`.
  `httpx` istemcisi istek URL'lerini INFO seviyesinde logluyor; Telegram Bot API URL
  bicimi token'i icerdigi icin **bot token'i duz metin olarak log dosyasina sizdi**.
  (Ayni risk Groq/OpenAI anahtarlari icin hata mesajlarinda da vardir.)
- **Karar**: `app.py` icinde `SecretRedactingFilter` (logging.Filter) tanimlandi; kok
  logger'in TUM handler'larina + `httpx`/`httpcore`/`uvicorn`/`uvicorn.access`/`telegram_bot`
  logger'larina baglandi. Temizlenen desenler:
  `bot\d{6,}:[A-Za-z0-9_-]{20,}` -> `bot[GIZLI]`,
  `(gsk|sk|xai|hf)[-_][A-Za-z0-9_-]{16,}` -> `[GIZLI_ANAHTAR]`.
  URL'in kalan kismi korunur (log hala teshis icin kullanilabilir).
- **Gerekce**: 9.4 - guvenlik (sir loglara/ekrana yazilmaz); 1.1 - gercek duzeltme.
- **Etki**: Eski log dosyasindaki token da temizlendi. Yeniden baslatma sonrasi loglarda
  `bot[GIZLI]` goruluyor, ham token YOK; yeni `tests/test_log_redaction.py` **6 PASS**
  (toplam **144 test PASS**). Telegram botu acilista otomatik basliyor:
  `Telegram bot started (running=True)`, `bot_username=maliyakbot`.

## D-022 - Kodlama Yoneticisi: sabit pipeline yerine gercek orkestrasyon motoru
- **Baglam**: Mevcut `/agents/team/run` sabit 3 cagrilik bir pipeline'di (uzman → denetci →
  lider); gorevi siniflandirmiyor, uzmanlari goreve gore secmiyor, dosya cakismasini
  engellemiyor, test kaniti toplamiyor, yeniden deneme yapmiyordu.
- **Karar**: `coding_manager.py` icinde deterministik bir orkestrasyon motoru yazildi:
  `classify_task` (8 gorev turu), `WORKFLOWS` (tur→uzman adimlari), adim-bazli en az yetki,
  `FileLockRegistry`, kalite kapisi (`run_verification` gercek komut + sinirli retry),
  11 alanli rapor, kalici gorev kaydi. Ajan personasina guvenmek yerine kararlar KODLA verilir.
- **Gerekce**: 1.1 gercek islev; 5 akilli yonlendirme; 7 bagimsiz kalite kapisi; 8 kontrollu
  otomatik duzeltme dongusu.
- **Etki**: `coding_routes.py` ile disa acildi. Mevcut `/agents/team/run` KORUNDU.

## D-023 - Adim-bazli EN AZ YETKI: `tools_override` + `_tools_payload` bos liste duzeltmesi
- **Baglam**: Araclari yalnizca ajan taniminda listelemek yetmiyordu; ayrica
  `_tools_payload()` bos listeyi "kisit yok = TUM araclar" diye yorumluyordu (guvenlik acigi).
- **Karar**: `ai_agent.chat`'e `tools_override` ve `system_prefix` parametreleri eklendi.
  `_tools_payload` semantigi: `None` → tum araclar; `[]` (bos liste) → HIC arac.
  Kodlama Yoneticisi plan modunda yazma adimlarina bile yalnizca salt-okuma araclarini verir.
- **Gerekce**: 10/11 - ajanlarin ihtiyaci olmayan araclara erismesini onle; en az yetki.
- **Etki**: Mevcut yollar `None` kullandigi icin davranis bozulmadi; 165 test PASS.

## D-024 - execute modu icin zorunlu onay (`confirm=true`)
- **Baglam**: Ajanlarin gercekten dosya yazmasi gereken durumlar var, ama izinsiz yazma riskli.
- **Karar**: `/api/v1/coding/run` `mode` alir: `plan` (varsayilan, HICBIR dosyayi degistirmez)
  ve `execute` (`confirm=true` gerektirir; aksi halde otomatik `plan`'a duser ve raporlanir).
- **Gerekce**: 11 - riskli islem icin onay; guvenli varsayilan.
- **Etki**: Testle dogrulandi: onaysiz execute → `mode=plan`.

## D-025 - Model yanitindaki "test gecti" iddiasi KANIT degildir
- **Baglam**: LLM'ler kanitsiz basari iddia edebilir; bu "sahte basari" riskidir.
- **Karar**: Rapor `6_test_sonuclari` bolumu yalnizca GERCEKTEN calistirilan dogrulama
  komutunun cikis kodunu kanit sayar. `verify_command` verilmediyse "iddia dogrulanmadi"
  notuyla `passed=null` yazilir; ajan iddiasi kanit yerine gecmez. `evidence-auditor` rolu
  ve Ana Yonetici incelemesi bunu bagimsizca denetler.
- **Gerekce**: 7/12.15 - test edilmeyen ozelligi basari sayma; 24 - kanit denetimi.
- **Etki**: Canli testte Ana Yonetici, kanit eksikligini acikca bildirdi.

## D-026 - 24 uzmanlik: mevcut ajanlari yeniden kullan, yalnizca eksikleri ekle
- **Baglam**: 24 uzmanlik alaninin tamami icin yeni ajan olusturmak gereksiz kopya uretirdi.
- **Karar**: 7 alan mevcut ajanlarla karsilandi (`coder`/`python-pro`, `backend-pro`,
  `frontend-pro`, `reviewer`, `security`, `devops`); gorev planlama `coding-manager`'a verildi;
  yalnizca GERCEKTEN eksik 19 kodlama uzmani eklendi (toplam 39 ajan). Esleme `custom_agents.py`
  icinde yorumla belgelendi.
- **Gerekce**: "Mevcut 20 ajani silme, gereksiz kopya olusturma, calisan sistemi bastan yazma."
- **Etki**: Roster testleri ">=20 + orijinaller korunur" seklinde guncellendi; mevcut ajanlar
  ve onlarin yonlendirmesi bozulmadi.

## D-027 - Arac allow-list'i executor duzeyinde ZORUNLU (derinlemesine savunma)
- **Baglam**: D-023 ile allow-list reklam duzeyinde daraltiliyordu ama `tool_executor.execute`
  izin kontrolu yapmiyordu; LLM allow-list disi bir araci cagirirsa yine calisiyordu.
- **Karar**: `ToolExecutor.execute(..., allowed: Optional[set])` eklendi. `allowed` verilirse ve
  arac adi kumede yoksa arac CALISTIRILMAZ (`success=False, denied=True`). `ai_agent.chat`
  etkin izin kumesini `_allowed_tool_names()` ile (`_tools_payload` ile birebir tutarli) gecirir.
  Davranis: `None` = kisit yok (tum araclar), `[]` = hic arac (fail-closed).
  Ic fallback cagrilari (generate_code/visual/video) `allowed=None` ile korunur.
- **Gerekce**: 10/11 - ajanlarin ihtiyaci olmayan araclara erismesini onle; 7 - bagimsiz savunma.
- **Etki**: `tests/test_tool_allowlist.py` **5 PASS**; toplam **170 PASS**; ana sohbet yolu
  canli testte bozulmadi (`/api/v1/ai/chat` 200, `success=true`). Commit `757af1e`.

## D-028 - Istek-yerel ajan durumu: `_active_tools`/`_active_model` -> contextvar
- **Baglam**: `NexusAIAgent` tekil (singleton). `_active_tools` ve `_active_model` instance
  attribute idi; iki eszamanli sohbet ayni anda farkli ajan/arac izni secerse son yazan
  digerini EZIYORDU. `parallel_analysis` adimlarinda da yaris riski vardi.
- **Karar**: Modul duzeyinde `_ACTIVE_TOOLS`/`_ACTIVE_MODEL` **ContextVar** tanimlandi; sinifa
  `_active_tools`/`_active_model` property (getter/setter) eklendi. Boylece mevcut kod/API
  degismeden her asyncio gorevi kendi context kopyasinda izole calisir.
- **Gerekce**: 8.4 - paralel gorev guvenligi; 1.1 - gercek yaris duzeltmesi.
- **Etki**: 2 yeni eszamanlilik testi; toplam **172 PASS**. Ana sohbet canli testte calisiyor
  (`/api/v1/ai/chat` 200, `success=true`). Commit `6bfacd7`.

## D-029 - Eksik uretim bagimliliklari `requirements.txt`'e eklendi
- **Baglam**: CI'daki `test` isi uc Python surumunde de dusuyordu. Temiz klon + temiz venv
  deneyi ile kok neden bulundu: `requirements.txt`'te `email-validator` yoktu. `auth_routes.py`
  ve `auth.py`, `pydantic.EmailStr` kullaniyor; paket yoksa `import pydantic` zinciri hata verir
  ve `import app` coker (testler collect asamasinda FAIL).
- **Karar**: `requirements.txt`'e `email-validator>=2.0.0` ve `python-multipart>=0.0.9`
  eklendi. Ikincisi `UploadFile = File(...)` uclari icin calisma zamaninda ZORUNLU.
- **Gerekce**: 10/11 ve 4.x - temiz makinede/bulutta uygulamanin ayaga kalkmasi; "tanimli !=
  calisiyor" ilkesi (yerel dev ortaminda tesadufen kurulu olan paketler artik bildiriliyor).
- **Etki**: `import app` temiz kurulumda calisiyor; CI yesil. Commit `c56bdb4`.

## D-030 - Testler ortam sir/anahtarlarina BAGIMLI OLMAMALI (hermetik test)
- **Baglam**: `test_call_llm_retries_429_then_succeeds` 3. denemede basari bekliyordu ama
  `_RATE_LIMIT_MAX_RETRIES=1` iken yalnizca 2 deneme yapiliyor. Test, ancak fallback zinciri
  ortamda gecerli bir API anahtari bulunca geciyordu; yerelde `OPENROUTER_API_KEY` ortam
  degiskeni oldugu icin yesil, CI'da anahtar olmadigi icin kirmiziydi.
- **Karar**: (a) Test, test edilen sabiti monkeypatch ile acikca sabitler. (b) Beklenmeyen yol
  (fallback) cagrilirsa test **basarisiz** olur; boylece ortam anahtari hatayi maskeleyemez.
- **Gerekce**: 9 - kanit/olculebilirlik; 10/11 - CI sinyali guvenilir olmali. Bir testin
  sonucu makinedeki ortam degiskenlerine veya kullanici config'ine gore degismemeli.
- **Etki**: Temiz klon + anahtarsiz ortamda 172 passed; CI (`563e7ab`) yesil. Commit `563e7ab`.

## D-031 - Ogrenme Ajani: denetimli, deterministik icgoru katmani
- **Baglam**: Kadroda `learning-agent` ("Ogrenme ve Gelisim Uzmani") tanimliydi ama
  gecmis gorev kayitlarindan sistematik icgoru ureten bir katman yoktu; `coding_manager`
  is akislarinda da hic kullanilmiyordu.
- **Karar**: `coding_insights.py` eklendi. Gecmis `coding_tasks.json` kayitlarindan
  DETERMINISTIK icgoru uretir (LLM/ag yok). Cikti **oneri**dir; onay/red insan kararidir.
  **Sinir**: modul yalnizca `coding_insights.json` yazar; kaynak kodu, `model_config.json`
  ve guvenlik kurallarini ASLA degistirmez. Onaylansa bile `applied` daima `False`.
- **Gerekce**: 7/11 - denetimsiz kendini-degistirme yasagi; 9 - kanit/olculebilirlik
  (deterministik cikti test edilebilir).
- **Etki**: 15 yeni test; toplam **187 PASS**. Rotalar `/api/v1/coding/insights*`.
  Gercek gorev kaydindan "kanitsiz tamamlama" icgorusu uretildi.

## D-032 - `search_learning` araci 405: POST -> GET (gercek arac hatasi)
- **Baglam**: `tool_executor.py` araci `/api/v1/learning/report` icin **POST** atiyordu,
  ancak endpoint `app.py`'da yalnizca **GET** olarak tanimli. Canli sunucuda dogrulandi:
  POST -> **405 Method Not Allowed**. Yani arac "tanimli" idi ama hic **calismiyordu**.
- **Karar**: Cagri GET'e cevrildi; non-200 yanit artik sahte basari yerine
  `success=False` + hata mesaji dondurur.
- **Gerekce**: 10/11 - "tanimli != calisiyor"; araclarin gercekten calismasi.
- **Etki**: Canli dogrulama `success=True` (rapor 1051 karakter). Regresyon testi
  `test_search_learning_tool_uses_get`; toplam **187 PASS**.

## D-033 - Icgoru kaliciligi: dedup + karar koruma + kanit tazeleme
- **Baglam**: Ayni analiz tekrar calistirilinca cift kayit olusmamali; insan karari
  (onay/red) yeni analizde kaybolmamali; ancak kaniti biten oneriler de yaniltici olmamali.
- **Karar**: Her icgoru tur+anahtar icin kararli `imza` (sha1) tasir. Yeniden analizde
  ayni imza **guncellenir** (kanit/gerekce tazelenir), karar ve kimlik korunur. Kaniti
  kalmayan kayitlar yalnizca hala `oneri` ise dusurulur; karar verilmisse **saklanir**
  (denetim izi).
- **Gerekce**: 9 - tekrar uretilebilirlik; 11 - karar kaydi guvenilirligi.
- **Etki**: `test_generate_persists_and_dedups`, `test_human_decision_survives_reanalysis`.

## D-034 - Yerel model yedekliligi: opt-in, loopback-only, tespit + adaptor
- **Baglam**: Tek bulut saglayicisi (`groq`) riskli: TPM/kota limiti veya ag/hesap sorunu
  tum sistemi kural-tabanli yanita dusuruyor. Yerel bir model bagimsiz yedek olurdu.
- **Karar**: `local_llm.py` eklendi: Ollama/LM Studio/llama.cpp gibi OpenAI-uyumlu yerel
  sunuculari tespit eder ve `_fallback_chain` sonunda (kural-tabanli yanittan once) dener.
  **Guvenlik**: yalnizca loopback adresler (`127.0.0.1`/`localhost`/`[::1]`), anahtar yok,
  `trust_env=False` (proxy atlanir). Yerel/kucuk modellere **tools gonderilmez** (bilincli
  sinirlama: metin yaniti).
- **Varsayilan KAPALI**: `NEXUS_LOCAL_LLM_URL` tanimli degilse hicbir ag cagrisi yapilmaz ve
  mevcut davranis birebir korunur. Bu, geriye donuk uyumluluk ve test izolasyonu icin sart.
- **Gerekce**: 10/11 - gercek yedeklilik ve "tanimli != calisiyor" (her yol gercekten test
  edildi); 7 - saglayici bagimliligi azalir.
- **Durum**: Adaptor + entegrasyon **PASS** (8 yeni test, toplam **195 PASS**; gercek yerel
  sunucuya karsi uctan uca dogrulandi). Gercek model agirliklari **BLOCKED**: bu makinede
  yerel calisma zamani yok ve donanim zayif (i5-5200U, 7.9 GB RAM, 940M 2 GB).
- **Etki**: `GET /api/v1/models/local/status`; `.env.example` guncellendi.

## D-035 - Tek servis dağıtımı: kök adres arayüze yönlendirir
- **Bağlam**: `/` rotası yalnızca JSON API bilgisi döndürüyordu. Render/yerel tek servis
  dağıtımında (D-020) kullanıcı adresi açtığında arayüz yerine JSON görüyordu.
- **Karar**: `root()` arayüz dosyası (`../sohbet.html`) varsa **302** ile `/sohbet.html`'e
  yönlendirir; yoksa eski JSON döner. API bilgisi `/api/info` rotasında **her zaman** erişilebilir.
- **Gerekçe**: 5 - tek adres yeterli; 10 - "tanımlı ≠ çalışıyor": dağıtım yolu gerçekten test
  edildi. Geriye dönük uyumlu: arayüzü kopyalanmayan Docker imajında davranış değişmez.
- **Güvenlik**: `.dockerignore` sır dosyalarını dışlar; `render.yaml` `AUTH_SECRET_KEY` ister
  (varsayılan geliştirme sırrı üretimde kullanılmasın).
- **Etki**: `test_root_ui.py` (5 test); toplam **200 PASS**.

## D-036 - Sağlayıcı devre kesici: 401/403 alan sağlayıcı atlanır
- **Bağlam**: Yalnızca `groq` geçerli; `openrouter`/`openai` anahtarları 401 dönüyor.
  `_fallback_chain` her fallback'te bu sağlayıcıların **tüm modellerini** deniyordu
  (17 + 5 = 22 istek, ölçülen **15.71 sn**).
- **Karar**: `provider_health.py` (süreç-yerel, bellek içi devre kesici):
  401/403 → sağlayıcı 30 dk atlanır; 404 → yalnızca model; 429 → yalnızca model
  (Retry-After, ≤60 sn); 5xx/timeout → **karar değişmez**.
- **Gerekçe**: 10 - gerçek ölçümle doğrulandı (22 istek/15.71 sn → **0/0.00 sn**);
  7 - tek sağlayıcıya bağımlılığın maliyeti azalır. Davranış korunur: ilk 401'de
  kardeş modeller yine denenir (model bazlı yetki olabilir); başarı işareti temizler.
- **Güvenlik**: anahtar/istek/yanıt metni **saklanmaz**; yalnızca HTTP kodu + etiket.
  Kalıcılık yok → süreç yeniden başlayınca sıfırlanır; anahtar panelden değişince
  `/api-key` `reset_provider()` çağırır.
- **Etki**: `/providers` + `status/cooldown_seconds/last_error/health`;
  `test_provider_health.py` (15 test) + `tests/conftest.py` (otomatik izolasyon);
  toplam **215 PASS**. Gerçek ikinci bulut sağlayıcı hâlâ BLOCKED (anahtar yok).

## D-037 - Öğrenme döngüsü görev sonunda otomatik (denetimli)
- **Bağlam**: İçgörü üretimi yalnızca elle (`POST /insights/analyze`) çalışıyordu;
  "geçmiş görev kayıtlarından **otomatik** içgörü" maddesi eksik kalıyordu.
- **Karar**: `coding_manager.run()` görevi kaydettikten sonra `_refresh_insights()`
  çağırır; sonuç `insights` alanında döner. LLM kullanılmaz, sonuç deterministiktir.
- **Sınır (değişmez)**: yalnızca `coding_insights.json` yazılır; `applied` daima `False`;
  kod/model/güvenlik kuralı **değiştirilmez**. Hata görevi **düşürmez**.
- **Kapatma**: `NEXUS_AUTO_INSIGHTS=0`. Testlerde varsayılan kapalı (`tests/conftest.py`)
  → gerçek çalışma verisi kirlenmez (hermetik test kuralı, D-030).
- **Gerekçe**: 4 - döngü gerçekten kapanır; 17 - denetimsiz öğrenme yok.
- **Etki**: `test_auto_insights.py` (4 test); toplam **219 PASS**.
  Canlı: 38.5 sn'lik gerçek görev → `insights.ok=True, analyzed=2, applied=False`.

## D-038 - Execute modu kaniti: dosya degisikligi arac sonucundan, nihai yanit kanittan
- **Baglam**: Gercek execute E2E kosusunda (izole proje) 3 kusur ortaya cikti:
  `files_changed` hep `[]`; "basarili" yazma adimi hic dosya yazmamis olabiliyor;
  dogrulama gecerken `final_answer` LLM'in 429 ozru olabiliyor.
- **Karar 1**: Degisen dosya listesi **yalnizca basarili `write_file`/`edit_file`
  arac sonucunun `path` alanindan** uretilir (ajan iddiasindan degil).
- **Karar 2**: Execute modunda yazma adimi basarili donup hicbir dosya degistirmediyse
  `9_kalan_riskler`e "kanitsiz yazma" uyarisi eklenir (gorev dusurulmez).
- **Karar 3**: LLM nihai metin uretemediyse `final_answer` **gercek kanittan** deterministik
  uretilir (dogrulama komutu + exit kodu + degisen dosyalar); `final_answer_note` isaretler.
- **Izolasyon**: Gercek E2E `NEXUS_WORKING_DIR` + `cwd` + gecici gorev/icgoru dosyalariyla
  ana repodan ayrisir; ana repo degismez.
- **Etki**: `test_files_changed.py` (6 test); toplam **225 PASS**.
  Canli 3. kosu: 120.3 sn, exit=0, bagimsiz pytest 5 passed.

## D-039 - Görev-yerel çalışma dizini (ContextVar) + açık güvenlik bulgusu
- **Bağlam**: `working_dir` yalnızca doğrulama komutunu yönlendiriyordu; araç yazımları
  ve `execute_command` proje köküne gidiyordu (canlı E2E'de doğrulandı).
- **Karar**: `tool_executor.task_working_dir` **ContextVar**; `ToolExecutor._root()`
  contextvar → örnek dizini sırasıyla çözer. `CodingTaskManager.run()` görev boyunca
  ayarlar, `finally` ile geri alır. Eşzamanlı görevler izole; sızıntı yok.
- **Sınır**: Yol çözümleme yine `realpath + commonpath` ile kök dışına çıkamaz.
- **Etki**: `test_task_working_dir.py` (7 test); toplam **232 PASS**.
  Canlı API: 94.5 sn, `exit=0`, dosya yalnızca görev dizininde; ana repo temiz.
- **AÇIK RİSK (kritik)**: `/api/v1/coding/*` kimlik doğrulaması **yok**. `execute` modu
  `shell=True` çalıştırdığı için API internete açılırsa uzaktan komut çalıştırma riski.
  Yerel kullanımda sınırlı; dağıtımdan önce kapatılmalı (opsiyonel `NEXUS_REQUIRE_AUTH`
  guard + arayüzde Bearer başlığı önerilir).

## D-040 - Kodlama kadrosunun tek kaynağı: 20 uzman + açık eksik bildirimi
- **Bağlam**: Kullanıcı tanımında 20 uzman var; sistemde 19'u vardı (Görev Planlama yoktu)
  ve 6 uzman hiçbir iş akışında çalışmıyordu.
- **Karar**: `custom_agents.CODING_SPECIALISTS` = resmî kadro (kullanıcı sırasıyla 20 kayıt,
  4/6/5/5 grupları). `coding_hierarchy()` yöneticileri + grupları döndürür; kayıtlı olmayan
  uzman `missing` alanında **açıkça** listelenir (sessiz yutma yok). `task-planner` eklendi.
- **Sınır**: Kadroya eklemek ajanı otomatik "çalışıyor" yapmaz; iş akışı bağı ayrıca kurulur
  (D-041) ve testle doğrulanır.
- **Etki**: `test_coding_team.py` (12 test); toplam **244 PASS**.

## D-041 - Görev türü yönlendirmesi: FRONTEND / DATABASE / DEVOPS
- **Bağlam**: `frontend-pro`, `database-pro`, `devops` kayıtlıydı ama hiçbir akışta yoktu.
- **Karar**: Üç yeni `TaskType` + deterministik anahtar kelime skoru. Öncelik sırası:
  SECURITY > BUGFIX > PERFORMANCE > API > FRONTEND > DATABASE > DEVOPS > REFACTOR >
  FEATURE > RESEARCH > GENERAL. Her tür kendi uzmanını **write=True** ile çalıştırır;
  test ve inceleme adımları zorunlu, regresyon/kanıt adımları opsiyonel.
- **Ek bağlar**: FEATURE -> `task-planner` (ilk) + `dependency-analyst`; API ->
  `task-planner` + `database-pro` (danışma); BUGFIX -> `dependency-analyst`.
- **Sınır**: Anahtar kelime yönlendirmesi deterministiktir; belirsiz istek `general` kalır.

## D-042 - Hiyerarşi arayüzde API'den gelir; öğrenme ajanı içgörüye işaretlenir
- **Karar**: Ajan seçim penceresi `/api/v1/agents/hierarchy` verisini kullanır ve
  Yönetim -> Kodlama Yöneticisi · 20 uzman -> A/B/C/D -> Diğer Ajanlar olarak render eder.
  Hiyerarşi istemcide elle yazılmaz (tek kaynak). `sohbet.html` script sürümü artırılır.
- **Öğrenme**: Otomatik içgörüler `agent="learning-agent"` alanıyla üretilir; LLM adımı
  değildir, `applied=False` kalır (D-031/D-037 korunur).
- **Kanıt**: Canlı `plan` koşusu 71.1 sn, `task_type=frontend`, uzman zinciri doğru,
  nihai yanıt Ana Yönetici'den; DOM'da 20 uzman ve 4 grup başlığı görünür.

## D-043 - Otomatik ajan seçimi = yalnızca Ana Yönetici Ajan
- **Bağlam**: Anahtar kelime seçicisi yanlış uzmana gidebiliyordu ("veritabanı şeması tasarla"
  → `designer`, "sohbet sayfasına arayüz bileşeni ekle" → `chat-pro`) ve kodlama zincirini
  tamamen atlıyordu.
- **Karar**: `auto_select_agent()` artık **daima** `main-manager` döndürür. Eski anahtar
  kelime mantığı `keyword_select_agent()` olarak korunur (ekip modu + yedek).
- **Gerçek devir**: `/api/v1/ai/chat` içinde otomatik seçim + kodlama görevi
  (`classify_task != GENERAL`) ise görev `CodingTaskManager.run(mode="plan",
  via_main_manager=True)` ile zincire verilir; yanıt Ana Yönetici'nin nihai raporudur.
  Genel sohbet tek ajan olarak kalır (hızlı).
- **Güvenlik**: Sohbetten gelen işler **plan** modundadır; `confirm` olmadığı için yazma
  yapılmaz (D-024). Uygulama için Kodlama Ekibi/execute gerekir.
- **Sınır**: `classify_task` anahtar kelime tabanlıdır; `GENERAL` kalan mesajlar zincire girmez.
- **Etki**: **249 PASS**; canlı: genel mesaj 1 sn (zincir yok), kodlama mesajı 79.1 sn
  (`task_type=frontend`; code-analyst → frontend-pro → test-engineer → reviewer →
  regression-tester; `mode=plan`), nihai yanıt Ana Yönetici'den.

## D-044 - Resmî kadro: 22 ajan; diğer 18 ajan kaldırıldı
- **Bağlam**: Kullanıcı, ana yönetici + kodlama yöneticisi + 20 uzman dışındaki **tüm**
  ajanların silinmesini istedi. Önceki kadro 40 ajandı; 18'i bu resmî listede değildi.
- **Karar**: `OFFICIAL_AGENT_IDS` = `main-manager`, `coding-manager` + `CODING_SPECIALISTS`
  (20). `DEFAULT_AGENTS` yalnızca bu 22 kaydı içerir. `REMOVED_AGENT_IDS` eski JSON'da
  kalan 18 ajanın yeniden yüklenmesini engeller.
- **Adlar**: Kullanıcı listesiyle birebir (`Kod Analiz Ajanı`, `Sistem Mimarisi Ajanı`, ...).
  `coding_hierarchy()` rol + ad alanlarını bu kadrodan üretir.
- **Bağlı düzeltmeler**: `coding_manager` içindeki `evidence-auditor` → `reviewer`,
  `tech-researcher` → `architect`; `team/run` lideri `main-manager`; anahtar kelime
  eşlemesi yalnızca resmî ID döndürür; bilinmeyen ajan ID'si `main-manager`'a yönlenir.
- **Arayüz**: Eski localStorage `assistant` değeri `main-manager`'a taşınır; ajan
  penceresi 22 kartı hiyerarşik gösterir, "Diğer Ajanlar" bölümü oluşmaz.
- **Sınır**: 18 ajanın kaynak tanım blokları AST ile **silindi** (1.565 -> 995 satır);
  `REMOVED_AGENT_IDS` yalnızca eski JSON için güvenlik ağıdır. `create_agent` API'si
  ileride yeni ajan eklemeye izin verir (bu görevde mevcut kadro temizlendi).
- **Etki**: **251 PASS**; `/api/v1/agents` 22, `/api/v1/agents/hierarchy` 20 uzman /
  `missing=[]`; gerçek tarayıcı DOM'unda 22 kart ve 4/6/5/5 grupları doğrulandı.

## D-045 - Otomatik/Ekip modu ve 5 bulut sağlayıcı kaldırıldı
- **Tarih**: 2026-10-21
- **Bağlam**: Kullanıcı, arayüzde ve akışta **Otomatik Ajan Seçimi** ile **Ekip Modu**nu
  istemedi; ayrıca Groq, OpenAI, Anthropic, Google Gemini ve Together AI sağlayıcılarının
  tamamen kaldırılmasını istedi. Tek bulut sağlayıcısı **OpenRouter**, birincil/fallback
  ise **yerel model** olacak.
- **Karar**:
  1. `sohbet.html` ve `js/app.js` içinden auto/ekip kartları, `TEAM_API`, `useTeam`,
     `selected_agent` gösterimi ve ilgili tıklama/başlık akışları kaldırıldı.
     `app.js?v=74`.
  2. Eski istemciler için `agent_id="auto"` yalnızca **`main-manager` takma adı**dır;
     istek bazlı otomatik uzman seçimi yapılmaz. Eski localStorage `auto`/`team`
     değerleri yüklemede `main-manager`'a taşınır.
  3. `/api/v1/agents/team/run`, `TeamRunRequest` ve `custom_agents.auto_select_agent`
     kaldırıldı. `keyword_select_agent()` yalnızca yardımcı/yedek olarak kaldı.
  4. `MODEL_CATALOG` yalnızca `openrouter` içerir. `ai_agent` başlangıcı, anahtar
     seçimi ve fallback zinciri OpenRouter + yerel modelle sınırlandı; ölü Gemini
     normalizasyon kodu kaldırıldı.
  5. Fallback, başarısız sağlayıcının **kardeş modellerini** önce dener. Tek bulut
     sağlayıcısı kaldığı için sert hatada sağlayıcıyı tamamen düşürmek yanlış olur;
     geçersiz anahtar `provider_health` tarafından ayrıca işaretlenir.
  6. Telegram varsayılanı `main-manager`; eski `/agent auto` komutu ve `auto` ayarı
     `main-manager`'a normalize edilir.
- **Gerekçe**: Ücretli API kullanmama, sırları koruma, tek sağlayıcıyla öngörülebilir
  maliyet ve kullanıcının istediği sade ajan/model arayüzü.
- **Alternatif**: Auto/ekip akışını yalnızca gizlemek (reddedildi: ölü endpoint ve
  yanlış yönlendirme riski kalırdı).
- **Etki / kanıt**: `248 PASS` (29 deselected); ruff `E9,F63,F7,F82` temiz;
  `node --check` OK. `/api/v1/agents` **22**, `/api/v1/agents/hierarchy` **20 uzman /
  missing=[]**, `/api/v1/models/catalog` ve `/providers` yalnızca **openrouter**.
  Gerçek Chromium DOM: **22 kart**, **1 sağlayıcı**, auto/ekip ve 5 sağlayıcı metni yok;
  localStorage `auto`/`team` -> `main-manager`. `/api/v1/agents/team/run` OpenAPI'de yok;
  kaldırılan sağlayıcılarla `/api-key` ve `/activate` **400** döndürür.
- **Sınır / açık**: OpenRouter anahtarı bu ortamda **401** veriyor; Ollama kapalı olduğu
  için canlı sohbet kural-tabanlı yedeğe düşüyor. `/api/v1/coding/*` kimlik doğrulaması
  ve `execute` `shell=True` riski duruyor (D-039). Yedek: `.ai-work/backups/ui-cleanup-20261021-002212/`.
