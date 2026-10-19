# NEXUS-CORE - Yerel durdurma scripti
# Kullanim:  powershell -ExecutionPolicy Bypass -File durdur.ps1
# Ne yapar: :8000 (backend), :8080, :8090 (masaustu) portlarini dinleyen surecleri durdurur.

Write-Host "== NEXUS-CORE durduruluyor ==" -ForegroundColor Cyan

$any = $false
foreach ($port in 8000, 8080, 8090) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) {
        $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        Write-Host ("  :{0} durduruluyor (PID {1} - {2})" -f $port, $c.OwningProcess, $p.ProcessName)
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
        $any = $true
    } else {
        Write-Host ("  :{0} zaten kapali" -f $port) -ForegroundColor DarkGray
    }
}

if ($any) { Write-Host "Durduruldu." -ForegroundColor Green } else { Write-Host "Calisan servis yok." -ForegroundColor Yellow }
