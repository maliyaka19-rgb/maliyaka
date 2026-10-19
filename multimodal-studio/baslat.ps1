# NEXUS-CORE - Yerel baslatma scripti
# Kullanim:  powershell -ExecutionPolicy Bypass -File baslat.ps1
# Ne yapar: backend'i (API + arayuz + Telegram botu) tek servis olarak :8000'de baslatir.

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $here "backend"
$log = Join-Path $backend "local_run.log"

Write-Host "== NEXUS-CORE yerel baslatma ==" -ForegroundColor Cyan

# Zaten calisiyor mu?
$existing = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
    Write-Host "Backend zaten calisiyor (PID $($existing.OwningProcess))." -ForegroundColor Yellow
} else {
    Write-Host "Backend baslatiliyor..."
    $env:PYTHONIOENCODING = "utf-8"
    Start-Process pwsh -ArgumentList "-NoExit", "-Command", "cd '$backend'; `$env:PYTHONIOENCODING='utf-8'; python run_server.py *>&1 | Tee-Object -FilePath '$log'" -WorkingDirectory $backend
}

# Hazir olana kadar bekle
Write-Host "Servis hazir bekleniyor..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-WebRequest "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 1000
}

if ($ready) {
    Write-Host ""
    Write-Host "HAZIR!" -ForegroundColor Green
    Write-Host "  Arayuz  : http://localhost:8000/sohbet.html" -ForegroundColor Green
    Write-Host "  API     : http://localhost:8000/api/v1/ai/chat" -ForegroundColor Green
    Write-Host "  Telegram: http://localhost:8000/telegram.html" -ForegroundColor Green
    Write-Host "  Log     : $log" -ForegroundColor DarkGray
    Start-Process "http://localhost:8000/sohbet.html"
} else {
    Write-Host "Backend baslatilamadi. Log: $log" -ForegroundColor Red
    if (Test-Path $log) { Get-Content $log -Tail 20 }
}
