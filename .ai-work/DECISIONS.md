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

