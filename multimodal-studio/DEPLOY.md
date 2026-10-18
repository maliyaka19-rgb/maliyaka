# NEXUS-CORE — Ücretsiz Dağıtım (Hosting) Kılavuzu

Bu belge, uygulamayı **ücretsiz** platformlara dağıtmanın gerçek yolunu ve
sınırlarını anlatır. Kod tarafındaki tüm hazırlıklar yapıldı ve test edildi;
**gerçek dağıtım** sizin hesabınız/API anahtarınız gerektirir.

---

## 1. Mimari

| Katman | Teknoloji | Örnek |
|--------|-----------|-------|
| Arayüz | Statik (HTML/CSS/JS) | `sohbet.html`, `chat.html`, `telegram.html` |
| Motor | FastAPI (Python 3.11) | `backend/app.py` |

**Backend, arayüzü de servis eder.** `backend/app.py` en sonunda statik dosyalar
`/` altına bağlanır (`StaticFiles`). Böylece arayüz ve API **aynı origin**'de
çalışır: CORS ayarı ve `config.js` düzenlemesi **gerekmez**.

Arayüz, backend adresini şu sırayla belirler:
1. `window.NEXUS_API_BASE` (config.js) — doluysa onu kullanır.
2. Sayfa `8080` (arayüz) veya `8090` (masaüstü) portundan geliyorsa → `<aynı-host>:8000`.
3. Aksi halde (backend arayüzü de servis ediyor: yerel 8000, tünel, hosting) → **aynı origin**.

Tek servis dağıtımı sayesinde ücretsiz platformda **tek** uygulama yeterlidir.

---

## 2. Ücretsiz platform seçenekleri

| Platform | Ne barındırır | Ücretsiz plan | Notlar |
|----------|---------------|---------------|--------|
| **Render** | Backend + Statik | ✅ var | 15 dk uyku; kalıcı disk yok |
| **Cloudflare Pages / Netlify / GitHub Pages** | Yalnız statik arayüz | ✅ sınırsız | Backend ayrı olmalı |
| **Fly.io** | Backend (Docker) | ⚠️ kredi bazlı | Kart doğrulaması isteyebilir |
| **Koyeb / Railway** | Backend (Docker) | ⚠️ değişken | Kart isteyebilir |
| **Hugging Face Spaces** | Backend (Docker) | ✅ var | Soğuk başlatma yavaş |

> ⚠️ **Önemli:** Yerel büyük model yok; uygulama LLM için dış API (Groq/OpenRouter)
> kullanır. Ücretsiz platformlar yalnızca **uygulamayı** barındırır, modeli değil.

---

## 3. Hazır dosyalar (bu repoda)

- `render.yaml` (repo kökü) — Render Blueprint (backend + statik).
- `backend/Dockerfile` — düzeltildi: artık **tüm** kaynağı kopyalar; `$PORT` okur.
- `backend/.dockerignore` — imajı küçük tutar, sırları dışlar.
- `backend/Procfile` — Heroku/Railway uyumlu başlatma.
- `backend/run_server.py` — artık **taşınabilir**: mutlak Windows yolu yok,
  `PORT`/`HOST` ortam değişkenlerini okur.
- `config.js` — arayüzün backend adresi.

---

## 3b. Ücretsiz ANLIK genel yayın (Cloudflare Quick Tunnel) — hesap GEREKMEZ

Kayıt, kart veya token olmadan uygulamayı **genel bir HTTPS adresine** açar:

```powershell
cd multimodal-studio
powershell -ExecutionPolicy Bypass -File .\tunnel.ps1
```

Çıktıdaki `https://<rastgele>.trycloudflare.com` adresini tarayıcıda açın.

Bu yol **gerçekten test edildi** (bkz. `.ai-work/V5-REPORT.md`): genel adres
üzerinden misafir girişi + gerçek LLM sohbeti 0 konsol hatasıyla çalıştı.

> ⚠️ Dürüst sınırlar: adres **geçicidir** ve her başlatmada değişir; pencere
> kapanınca yayın durur; tünel ara sıra kısa süreli kopabilir (birkaç saniye
> içinde kendini toparlar). Kalıcı adres için aşağıdaki Render yolu gerekir.

---

## 4. Render ile kalıcı dağıtım (adım adım)

Arayüz de backend'den servis edildiği için **tek servis** yeterlidir.

1. Kodu bir GitHub deposuna gönderin (`multimodal-studio/` ve `render.yaml` dahil).
2. [render.com](https://render.com) → **New +** → **Blueprint** → depoyu seçin.
3. Render `render.yaml`'ı okur ve servisi oluşturur (Docker).
4. Panelde şu gizli değerleri girin:
   - `GROQ_API_KEY` → Groq konsolundan aldığınız anahtar
   - `NEXUS_ENCRYPTION_PASSPHRASE` → rastgele uzun bir parola
5. Uygulamayı açın: `https://<servis-adiniz>.onrender.com/`
   (arayüz aynı adresten gelir; `config.js` düzenlemeye gerek yok)
6. Sağlığı doğrulayın: `https://<servis-adiniz>.onrender.com/health`

---

## 5. Docker ile yerel doğrulama (dağıtımdan önce)

```bash
cd multimodal-studio/backend
docker build -t nexus-backend .
docker run -p 8000:8000 -e GROQ_API_KEY=... nexus-backend
# Ayrı terminal:
curl http://localhost:8000/health
```

---

## 6. Bilinen sınırlar (dürüst durum)

- **Dosya sistemi özellikleri** (proje açma, dosya ağacı, editör) yerel
  makineye erişir; uzak hostingde kullanıcının diski olmadığı için sınırlıdır.
- **Kalıcı disk yok** (ücretsiz plan): `brain_data/`, `learning_registry/`,
  `generated_videos/` yeniden başlatmada sıfırlanır.
- **Şifreli yapılandırma** (`model_config.json`) yerel anahtarla yazılmıştır;
  hostingde anahtarları **ortam değişkeni** olarak verin.
- `moviepy`/`ffmpeg` içeren video üretimi CPU yoğundur; ücretsiz planda yavaştır.

## 7. Durum

| Öğe | Durum |
|-----|-------|
| Kod hazırlığı (Dockerfile, Procfile, render.yaml, taşınabilir başlatıcı) | ✅ PASS (test edildi) |
| Arayüz API adresi yapılandırılabilir | ✅ PASS |
| **Ücretsiz genel yayın (Cloudflare Quick Tunnel, hesapsız)** | ✅ **PASS** — genel HTTPS adresinde uçtan uca çalıştı |
| Kalıcı ücretsiz bulut dağıtımı (Render vb.) | ⛔ BLOCKED — platform hesabı + API anahtarı gerekir |
