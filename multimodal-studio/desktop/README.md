# NEXUS-CORE — Masaüstü Uygulaması (Electron)

`multimodal-studio` arayüzünü tek tıkla açan masaüstü kabuğu. Python backend'i
otomatik başlatmayı dener, arayüzü yerel bir HTTP sunucusundan servis eder.

## Dosyalar
| Dosya | Görev |
|-------|-------|
| `main.js` | Electron ana süreç: pencere, menü, backend başlatma |
| `preload.js` | Güvenli köprü (`window.nexusDesktop`) |
| `static-server.js` | Bağımlılıksız statik sunucu (test edilebilir) |
| `test-server.js` | `node test-server.js` — statik sunucu testi (6/6) |
| `package.json` | Electron + electron-builder yapılandırması |

## Çalıştırma

```powershell
cd multimodal-studio\desktop
npm install                 # bağımlılıklar
npm start                   # uygulamayı başlat
node test-server.js         # statik sunucu testi
```

## Paketleme (Windows kurulum + taşınabilir)

```powershell
npm run dist                # NSIS kurulum + portable .exe  -> desktop\dist\
```

## Davranış
- Backend zaten çalışıyorsa (port 8000 dolu) **dokunmaz**.
- Çalışmıyorsa `backend/run_server.py`'yi uygun Python ile başlatır.
- Dış bağlantılar (Telegram, GitHub) sistem tarayıcısında açılır.
- Ortam değişkenleri:
  - `MCS_BACKEND_URL` (varsayılan `http://localhost:8000`)
  - `MCS_STATIC_PORT` (varsayılan `8090`; doluysa otomatik boş port)
  - `MCS_SKIP_BACKEND=1` — backend'i hiç başlatma

## Menü
- **Dosya**: Yenile / Zorla Yenile / Çıkış
- **Görünüm**: Yakınlaştırma, Tam Ekran, Geliştirici Araçları
- **Yardım**: “Backend durumu” canlı kontrol + hakkında

## Güvenlik
- `contextIsolation: true`, `nodeIntegration: false`.
- Statik sunucu path traversal'ı engeller (test edildi).
- Token/anahtar dosyaları pakete dahil edilmez.
