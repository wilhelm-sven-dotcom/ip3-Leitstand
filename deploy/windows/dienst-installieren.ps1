# Einrichtung des ip3 Leitstands als Windows-Dienst.
#
# Dieses Skript ist als Nachschlagewerk gedacht und fuehrt sich nicht von selbst aus:
# es zeigt die Befehle an, damit niemand sie aus dem Gedaechtnis tippt. Erlaeuterungen
# stehen in NSSM-Einrichtung.md, insbesondere der Hinweis zum Dienstkonto und OneDrive.
#
# Aufruf:  .\dienst-installieren.ps1 -Ausfuehren   (ohne Schalter wird nur angezeigt)

param(
    [switch]$Ausfuehren,
    [string]$Wurzel = "D:\ip3-leitstand",
    [string]$Nssm = "C:\Tools\nssm\nssm.exe",
    [string]$Caddy = "C:\Tools\caddy\caddy.exe"
)

$befehle = @(
    "$Nssm install ip3-leitstand `"$Wurzel\backend\.venv\Scripts\ip3-leitstand.exe`" server",
    "$Nssm set ip3-leitstand AppDirectory $Wurzel",
    "$Nssm set ip3-leitstand AppEnvironmentExtra IP3_CONFIG=$Wurzel\config.toml",
    "$Nssm set ip3-leitstand DisplayName `"ip3 Leitstand`"",
    "$Nssm set ip3-leitstand Start SERVICE_AUTO_START",
    "$Nssm set ip3-leitstand AppStdout $Wurzel\logs\dienst-ausgabe.log",
    "$Nssm set ip3-leitstand AppStderr $Wurzel\logs\dienst-fehler.log",
    "$Nssm set ip3-leitstand AppRotateFiles 1",
    "$Nssm set ip3-leitstand AppRotateBytes 10485760",
    "$Nssm set ip3-leitstand AppExit Default Restart",
    "$Nssm set ip3-leitstand AppRestartDelay 5000",
    "$Nssm install ip3-caddy `"$Caddy`" run --config $Wurzel\deploy\Caddyfile",
    "$Nssm set ip3-caddy Start SERVICE_AUTO_START"
)

Write-Host ""
Write-Host "Befehle zur Einrichtung:" -ForegroundColor Cyan
foreach ($befehl in $befehle) { Write-Host "  $befehl" }
Write-Host ""
Write-Host "Danach noch von Hand:" -ForegroundColor Yellow
Write-Host "  1. Dienstkonto setzen (siehe NSSM-Einrichtung.md, Abschnitt 3)"
Write-Host "  2. $Caddy trust     (Zertifizierungsstelle bekannt machen)"
Write-Host "  3. .\firewall-regel.ps1 -Subnetz <Buero-Subnetz>"
Write-Host "  4. ip3-leitstand backup   als Dienstkonto, und im Zielordner nachsehen"
Write-Host ""

if (-not $Ausfuehren) {
    Write-Host "Nur angezeigt. Mit -Ausfuehren werden die Befehle ausgefuehrt." -ForegroundColor Green
    exit 0
}

foreach ($befehl in $befehle) {
    Write-Host "-> $befehl"
    Invoke-Expression $befehl
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Abgebrochen: der letzte Befehl endete mit Code $LASTEXITCODE."
        exit $LASTEXITCODE
    }
}
Write-Host "Dienste eingerichtet. Starten mit: $Nssm start ip3-leitstand" -ForegroundColor Green
