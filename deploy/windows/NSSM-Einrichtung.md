# Windows-Dienst mit NSSM einrichten

Für den Bürorechner, der den Leitstand betreibt. NSSM (Non-Sucking Service Manager) macht aus
einem Programm einen Windows-Dienst mit Autostart – ohne ihn müsste sich jemand am Rechner
anmelden, damit der Leitstand läuft.

Download: <https://nssm.cc/download>. Die Datei `nssm.exe` (64 Bit) nach `C:\Tools\nssm\`
entpacken.

> **Die häufigste Stolperfalle steht am Anfang, weil sie den meisten Ärger macht:**
>
> **Ein Dienst, der unter `LocalSystem` läuft, erreicht den OneDrive-Ordner des angemeldeten
> Nutzers nicht.** Das Backup schlägt dann jede Nacht fehl – ohne dass jemand es merkt, denn
> niemand schaut in die Protokolle. Zwei Wege heraus:
>
> 1. Den Dienst unter einem eigenen Windows-Konto laufen lassen, das ein Profil samt
>    OneDrive-Anbindung besitzt (empfohlen), **oder**
> 2. das Backup-Ziel außerhalb eines Nutzerprofils wählen – etwa einen Ordner, den der
>    OneDrive-Client des Firmenkontos synchronisiert.
>
> Nach der Einrichtung einmal `ip3-leitstand backup` **als Dienstkonto** ausführen und
> nachsehen, ob die Datei im Zielordner ankommt. Der Datenstand auf der Startseite zeigt es
> anschließend ebenfalls.

## Voraussetzungen

| Was | Wofür |
|---|---|
| Python 3.11 oder neuer | Backend |
| Node 22 | nur zum Bauen der Oberfläche, nicht im Betrieb nötig |
| Caddy | TLS und Reverse Proxy (`deploy/Caddyfile`) |
| NSSM | Dienste |

## 1. Verzeichnisse anlegen

```
D:\ip3-leitstand\            Programm, Konfiguration
D:\ip3-leitstand\daten\      SQLite-Datenbank (lokal, niemals in OneDrive)
D:\ip3-leitstand\logs\       Protokolle
```

Das Dienstkonto braucht Schreibrechte auf `daten\`, `logs\` und den Backup-Ordner.

## 2. Leitstand einrichten

```powershell
cd D:\ip3-leitstand\backend
uv sync --frozen
uv run alembic upgrade head
uv run ip3-leitstand seed          # legt Firma, Rollen und den ersten Administrator an
```

Das ausgegebene Passwort notieren – es erscheint nur einmal und muss bei der ersten Anmeldung
gewechselt werden.

Oberfläche bauen:

```powershell
cd D:\ip3-leitstand\frontend
npm ci
npm run build
```

Danach in `config.toml` unter `[pfade]` den Eintrag `frontend` auf
`D:\ip3-leitstand\frontend\dist` setzen.

## 3. Dienst einrichten

Die Befehle stehen auch in `dienst-installieren.ps1`. Das Skript führt sich nicht selbst aus –
es ist als Nachschlagewerk gedacht, damit niemand aus dem Gedächtnis tippt.

```powershell
nssm install ip3-leitstand "D:\ip3-leitstand\backend\.venv\Scripts\ip3-leitstand.exe" server
nssm set ip3-leitstand AppDirectory D:\ip3-leitstand
nssm set ip3-leitstand AppEnvironmentExtra IP3_CONFIG=D:\ip3-leitstand\config.toml
nssm set ip3-leitstand DisplayName "ip3 Leitstand"
nssm set ip3-leitstand Description "Projekt- und Finanz-Cockpit der ip3 Energietechnik GmbH"
nssm set ip3-leitstand Start SERVICE_AUTO_START
nssm set ip3-leitstand AppStdout D:\ip3-leitstand\logs\dienst-ausgabe.log
nssm set ip3-leitstand AppStderr D:\ip3-leitstand\logs\dienst-fehler.log
nssm set ip3-leitstand AppRotateFiles 1
nssm set ip3-leitstand AppRotateBytes 10485760
nssm set ip3-leitstand AppExit Default Restart
nssm set ip3-leitstand AppRestartDelay 5000
```

Dienstkonto setzen (siehe Hinweis oben):

```powershell
nssm set ip3-leitstand ObjectName "IP3\dienst-leitstand" "PASSWORT"
```

Caddy ebenfalls als Dienst:

```powershell
nssm install ip3-caddy "C:\Tools\caddy\caddy.exe" run --config D:\ip3-leitstand\deploy\Caddyfile
nssm set ip3-caddy Start SERVICE_AUTO_START
```

Einmalig die Zertifizierungsstelle von Caddy dem System bekannt machen:

```powershell
C:\Tools\caddy\caddy.exe trust
```

## 4. Firewall

Nur Port 443 und nur aus dem Büro-Netz. Port 8000 bleibt geschlossen – der Leitstand lauscht
dort ausschließlich lokal, Caddy vermittelt. Befehle in `firewall-regel.ps1`.

## 5. Starten und prüfen

```powershell
nssm start ip3-leitstand
nssm start ip3-caddy
```

Dann `https://leitstand.ip3.local/api/gesundheit` im Browser aufrufen: dort muss
`{"status":"bereit", ...}` erscheinen. Danach anmelden und den Datenstand auf der Startseite
ansehen.

## 6. Arbeitsplätze

Das Wurzelzertifikat der Caddy-Zertifizierungsstelle auf jedem Arbeitsplatz in
„Vertrauenswürdige Stammzertifizierungsstellen" importieren – per Gruppenrichtlinie oder von
Hand. Es liegt auf dem Host unter
`C:\Windows\System32\config\systemprofile\AppData\Roaming\Caddy\pki\authorities\local\root.crt`
(bei einem Dienstkonto im Profil dieses Kontos).

Ohne diesen Schritt zeigt jeder Browser eine Zertifikatswarnung.
