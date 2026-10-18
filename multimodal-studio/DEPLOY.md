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

Arayüz, backend adresini `config.js` içindeki `window.NEXUS_API_BASE` üzerinden
okur. **Yerelde hiçbir ayar gerekmez** (otomatik `http://localhost:8000`).

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

## 4. Render ile dağıtım (adım adım)

1. Kodu bir GitHub deposuna gönderin (`multimodal-studio/` ve `render.yaml` dahil).
2. [render.com](https://render.com) → **New +** → **Blueprint** → depoyu seçin.
3. Render `render.yaml`'ı okur ve iki servis oluşturur.
4. Panelde şu gizli değerleri girin:
   - `GROQ_API_KEY` → Groq konsolundan aldığınız anahtar
   - `NEXUS_ENCRYPTION_PASSPHRASE` → rastgele uzun bir parola
   - `CORS_ALLOW_ORIGINS` → örn. `https://nexus-core-ui.onrender.com`
5. Statik sitenin `config.js` dosyasında backend adresini yazın:
   ```js
   window.NEXUS_API_BASE = "https://nexus-core-backend.onrender.com";
   ```
6. Backend sağlığını doğrulayın: `https://nexus-core-backend.onrender.com/health`

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
| Gerçek buluta dağıtım | ⛔ BLOCKED — platform hesabı/kimlik doğrulama ve API anahtarı gerekir |
