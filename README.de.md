# VeSync mit Cosori Turbo Tower Pro

[English](README.md)

Fork der offiziellen Home-Assistant-Integration **VeSync** mit Unterstützung für den **Cosori Turbo Tower Pro Smart** (CAF-DC111S-AEU / CAF-DC113S-ADE), einen Airfryer mit zwei Körben.

> **Inoffiziell.** Ersetzt die eingebaute VeSync-Integration (gleiche Domain `vesync`). Bestehende Anmeldung und Geräte (z. B. Luftreiniger) bleiben erhalten. Ziel ist, alles über [pyvesync](https://github.com/webdjoe/pyvesync) und Home Assistant Core zurückzugeben – dann wird dieser Fork überflüssig. Keine Verbindung zu VeSync oder COSORI und nicht von ihnen unterstützt; Produktnamen sind Marken ihrer jeweiligen Inhaber.

## Sicherheit

> [!WARNING]
> **Fernstart auf eigene Gefahr.** *Starten* und `vesync.start_cook` mit `send_only: false` heizen sofort los, ohne dass jemand am Gerät ist. In der EU verlangt die VeSync-App, den Garvorgang mit der Start/Pause-Taste am Gerät zu starten (IEC/EN 60335-1, IEC/EN 60335-2-9). So arbeiten *An Gerät senden* und standardmäßig `vesync.start_cook`: Die Einstellungen werden übertragen, gestartet wird mit der Taste am Gerät. Die Buttons *Starten* und *Beide starten* sind deshalb bei Neuinstallationen deaktiviert; wer aus der Ferne starten will, aktiviert sie unter den Entitäten des Geräts. Das Gerät beim Garen nie unbeaufsichtigt lassen.
>
> Die Integration wird ohne Gewährleistung und Haftung bereitgestellt, siehe [Lizenz](LICENSE).

## Was dazukommt

Aufgebaut wie die Core-Integrationen für Backöfen (Home Connect, Miele) und auf dem Core-Modell „je Korb“ ([home-assistant/core#191014](https://github.com/home-assistant/core/pull/191014)), damit es später ohne große Änderungen in Core passt.

- Sensoren je Korb wie in Core: Kochstatus, eingestellte Temperatur und Zeit, aktuelle Temperatur, dazu **„fertig um“**
- Ein am Gerät gewähltes, noch nicht gestartetes Programm bleibt sichtbar (Status „Standby“ mit Werten)
- Schnellere Abfrage, solange ein Korb aktiv ist
- Programm (Auswahlliste), Temperatur und Zeit je Korb; Werte kommen aus den Standards des Geräts
- Buttons je Korb: **Starten** (legt sofort los, standardmäßig deaktiviert), **An Gerät senden** (Start mit der Taste am Gerät), Pausieren, Fortsetzen, Stoppen
- Für beide Körbe: Startmodus (Unabhängig, Sync = gemeinsames Ende, Match), Beide starten, Beide an Gerät senden, Alle pausieren, Alle fortsetzen, Alle stoppen, Sync beenden
- Ereignisse je Korb für Automationen: bereit, gestartet, pausiert, fortgesetzt, Korb gezogen, fertig, abgebrochen
- Firmware-Anzeige für den Airfryer
- Aktionen für Rezepte:
  - `vesync.start_cook` – ein Korb oder beide (Unabhängig, Sync, Match); leere Werte = Gerätestandard; sendet standardmäßig nur an das Gerät; `send_only: false` startet sofort
  - `vesync.set_preset`, `vesync.reset_preset` – Programm-Standards im Gerät ändern/zurücksetzen

Gut zu wissen: Ein Programm, das am Bedienfeld gewählt, aber nicht gestartet wurde, lässt sich nur am Gerät abbrechen – die Cloud lehnt das Stoppen ab. Was aus Home Assistant gesendet wurde, lässt sich stoppen.

Beispiel Rezept-Script:

```yaml
action: vesync.start_cook
data:
  basket: "1"
  program: airfry
  temperature: 200
  duration: 18
```

### Karte und Rezepte

Für ein fertiges Dashboard gibt es eine eigene Karte, die [VeSync Air Fryer Card](https://github.com/KindOfNerdy/vesync-airfryer-card): Status, Bedienung beider Körbe und Rezeptliste in einer Karte, installierbar über den Marketplace. Im selben Repository liegt ein Skript-Blueprint („Turbo Tower recipe“), der Rezepte wie das Beispiel oben ohne YAML anlegt.

### Umstieg von 0.3.x

Version 0.4.0 benennt „Zone“ in „Korb“ um und ersetzt Entitäten: neue Entity-IDs, der Schalter „Direktstart“ entfällt (dafür die Buttons „An Gerät senden“), Pause/Fortsetzen sind getrennte Buttons, die Aktionen `stop`, `pause`, `resume` und `quit_sync` entfallen (Buttons nutzen). In `start_cook` heißt `zone` jetzt `basket`, `direct_start` wird zu `send_only`. Alte Entitäten unter *Einstellungen → Geräte* entfernen und Dashboards/Automationen anpassen.

## Korrekturen gegenüber pyvesync 3.5.1

Basiert auf pyvesync 3.5.1 (enthält inzwischen Pause/Fortsetzen, Sync/Match, `cookEnd` und die Absturz-Korrektur aus unseren Beiträgen). Nur noch angewendet, solange pyvesync sie braucht:

- Backen ab 80 °C wie in der Anleitung ([#598](https://github.com/webdjoe/pyvesync/issues/598))
- Firmware des Airfryers wird mit abgefragt ([#601](https://github.com/webdjoe/pyvesync/pull/601))
- Am Bedienfeld gewähltes, nicht gestartetes Programm behält seine Werte (statt wie „Aus“ auszusehen)

## Installation

1. Im Marketplace (HACS) dieses Repository als benutzerdefiniertes Repository vom Typ *Integration* hinzufügen.
2. „VeSync (Turbo Tower)“ installieren und bestätigen, dass die eingebaute Integration ersetzt wird.
3. Home Assistant neu starten.

Zurück zur offiziellen Integration: im Marketplace entfernen und neu starten.

## Lizenz

Apache-2.0, wie Home Assistant Core. Basis: `homeassistant/components/vesync` aus home-assistant/core (siehe `custom_components/vesync/UPSTREAM.md`).
