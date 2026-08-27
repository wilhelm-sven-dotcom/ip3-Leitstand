# Firewall-Regel fuer den ip3 Leitstand.
#
# Nur Port 443 und nur aus dem Buero-Netz. Port 8000 bleibt geschlossen: der Leitstand
# lauscht dort ausschliesslich lokal, Caddy vermittelt von aussen (PLAN 2).

param(
    [Parameter(Mandatory = $true)]
    [string]$Subnetz,   # z. B. 192.168.10.0/24
    [switch]$Ausfuehren
)

$befehl = "New-NetFirewallRule -DisplayName 'ip3 Leitstand (HTTPS)' " +
          "-Direction Inbound -Action Allow -Protocol TCP -LocalPort 443 " +
          "-RemoteAddress $Subnetz -Profile Domain,Private"

Write-Host ""
Write-Host "Regel:" -ForegroundColor Cyan
Write-Host "  $befehl"
Write-Host ""
Write-Host "Pruefen, dass Port 8000 nicht offen ist:" -ForegroundColor Yellow
Write-Host "  Get-NetFirewallRule | Where-Object DisplayName -like '*8000*'"
Write-Host ""

if (-not $Ausfuehren) {
    Write-Host "Nur angezeigt. Mit -Ausfuehren wird die Regel angelegt." -ForegroundColor Green
    exit 0
}

Invoke-Expression $befehl
Write-Host "Regel angelegt." -ForegroundColor Green
