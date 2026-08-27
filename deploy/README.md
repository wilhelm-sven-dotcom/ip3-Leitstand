# Betriebsunterlagen

Vorlagen für den Betrieb auf dem Bürorechner. Der vollständige Ablauf steht im
[RUNBOOK](../RUNBOOK.md); hier liegen die Dateien, auf die es sich bezieht.

| Datei | Zweck |
|---|---|
| `Caddyfile` | Reverse Proxy mit TLS für die Produktivinstanz |
| `Caddyfile.testinstanz` | dasselbe für die Testinstanz auf Port 8010 |
| `systemd/ip3-leitstand.service` | Dienst unter Linux |
| `windows/NSSM-Einrichtung.md` | Schritt-für-Schritt-Anleitung für den Windows-Dienst |
| `windows/dienst-installieren.ps1` | die NSSM-Befehle als Skript (zeigt sie an, führt sie nur mit `-Ausfuehren` aus) |
| `windows/firewall-regel.ps1` | Port 443 nur für das Büro-Netz freigeben |

## Drei Punkte, die den meisten Ärger machen

**TLS ist nicht optional.** Der Leitstand führt Anmeldungen über ein Cookie. Ohne TLS geht es
unverschlüsselt durchs Firmennetz, und wer im Netz mitliest, kann eine Sitzung übernehmen.
Caddy erzeugt mit `tls internal` ein eigenes Zertifikat – dessen Wurzelzertifikat muss auf
jedem Arbeitsplatz installiert werden, sonst warnt der Browser. Nutzer, die Warnungen
wegklicken, klicken auch die nächste weg.

**Genau ein Arbeitsprozess.** Der Zeitplan für die nächtlichen Läufe steckt im Prozess. Mit
mehreren Prozessen liefe die Sicherung mehrfach, später auch die Importe – letzteres würde
Kosten doppelt zählen. Der Startbefehl trägt deshalb kein `--workers`, und die Anwendung warnt
im Protokoll, wenn sie Anzeichen für mehrere Prozesse findet.

**Das Dienstkonto muss den Backup-Ordner erreichen.** Unter Windows ist das die häufigste
Ursache für eine Sicherung, die jede Nacht scheitert: ein Dienst unter `LocalSystem` sieht das
OneDrive des angemeldeten Nutzers nicht. Einzelheiten in `windows/NSSM-Einrichtung.md`.

## Anpassen

Die Vorlagen enthalten Beispielpfade (`D:\ip3-leitstand`, `/opt/ip3-leitstand`,
`leitstand.ip3.local`). Sie werden vor der Verwendung an den Host angepasst – die
Anwendung selbst kennt keine Pfade, alles steht in der `config.toml`.
