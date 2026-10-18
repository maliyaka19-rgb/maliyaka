# ============================================================
#  NEXUS-CORE — ÜCRETSİZ GENEL YAYIN (Cloudflare Quick Tunnel)
# ============================================================
#  Hesap, kart veya token GEREKMEZ. Bu betik:
#    1) cloudflared yoksa indirir,
#    2) backend :8000 üzerinde genel bir HTTPS adresi açar,
#    3) adresi ekrana yazar.
#
#  Kullanım:
#      cd multimodal-studio
#      powershell -ExecutionPolicy Bypass -File .\tunnel.ps1
#
#  NOTLAR (dürüst):
#   - Üretilen adres GEÇİCİDİR ve her başlatmada değişir.
#   - Bu pencere kapanınca yayın durur (makine açık olmalı).
#   - Backend hem API'yi hem arayüzü servis eder; tek adres yeterlidir.
# ============================================================

$ErrorActionPreference = "Stop"

$port = if ($env:PORT) { $env:PORT } else { "8000" }
$dir  = Join-Path $env:LOCALAPPDATA "nexus-core\cloudflared"
$exe  = Join-Path $dir "cloudflared.exe"

# 1) Backend çalışıyor mu?
try {
    $h = Invoke-WebRequest "http://localhost:$port/health" -TimeoutSec 5 -UseBasicParsing
    Write-Host "[ok] Backend çalışıyor (port $port, durum $($h.StatusCode))" -ForegroundColor Green
} catch {
    Write-Host "[hata] Backend yanıt vermiyor: http://localhost:$port/health" -ForegroundColor Red
    Write-Host "       Önce şunu çalıştırın:  cd backend; python run_server.py" -ForegroundColor Yellow
    exit 1
}

# 2) cloudflared
if (-not (Test-Path $exe)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Write-Host "[..] cloudflared indiriliyor (tek seferlik)…"
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing
    Write-Host "[ok] İndirildi: $exe" -ForegroundColor Green
}

# 3) Tünel
Write-Host ""
Write-Host "Genel adres birazdan aşağıda görünecek (https://....trycloudflare.com)" -ForegroundColor Cyan
Write-Host "Kapatmak için: Ctrl+C" -ForegroundColor Cyan
Write-Host ""
& $exe tunnel --url "http://localhost:$port" --no-autoupdate
