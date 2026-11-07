# VeSync mit Cosori Turbo Tower Pro

[English](README.en.md)

Fork der offiziellen Home-Assistant-Integration **VeSync** mit Unterstützung für den **Cosori Turbo Tower Pro Smart** (CAF-DC111S-AEU / CAF-DC113S-ADE), einen Airfryer mit zwei Garzonen.

> **Inoffiziell.** Ersetzt die eingebaute VeSync-Integration (gleiche Domain `vesync`). Bestehende Anmeldung und Geräte (z. B. Luftreiniger) bleiben erhalten. Ziel ist, alles über [pyvesync](https://github.com/webdjoe/pyvesync) und Home Assistant Core zurückzugeben – dann wird dieser Fork überflüssig.

## Was dazukommt

- Status je Zone (Aus, Bereit, Gart, Pausiert, Wartet, Korb offen, Fertig)
- „Fertig um“ je Zone
- Modus (Getrennt, Match, Sync)
- Schnellere Abfrage, solange eine Zone aktiv ist
- Programm (Auswahlliste), Temperatur und Zeit je Zone; Werte kommen aus den Standards des Geräts
- Startmodus für beide Zonen: Getrennt, Sync (gemeinsames Ende), Match
- „Start am Gerät bestätigen“ (Standard an): Programm wird nur gesendet, gestartet wird am Gerät
- Buttons: Zone starten, beide starten, Zone stoppen, alle stoppen, Pause/Fortsetzen
- Ereignisse je Zone für Automationen: bereit, gestartet, pausiert, fortgesetzt, Korb gezogen, fertig, abgebrochen
- Firmware-Anzeige für den Airfryer

In Arbeit: Services für Rezepte und Automationen.

## Korrekturen gegenüber pyvesync 3.5.0

Werden nur angewendet, solange pyvesync sie noch braucht:

- Nicht unterstützte Geräte im Konto verhindern nicht mehr, dass andere Geräte erkannt werden ([#589](https://github.com/webdjoe/pyvesync/pull/589))
- Garende (`cookEnd`) wird erkannt ([#590](https://github.com/webdjoe/pyvesync/pull/590))
- Backen ab 80 °C wie in der Anleitung ([#598](https://github.com/webdjoe/pyvesync/issues/598))
- Firmware des Airfryers wird mit abgefragt

## Installation

1. Im Marketplace (HACS) dieses Repository als benutzerdefiniertes Repository vom Typ *Integration* hinzufügen.
2. „VeSync (Turbo Tower)“ installieren und bestätigen, dass die eingebaute Integration ersetzt wird.
3. Home Assistant neu starten.

Zurück zur offiziellen Integration: im Marketplace entfernen und neu starten.

## Lizenz

Apache-2.0, wie Home Assistant Core. Basis: `homeassistant/components/vesync` aus home-assistant/core (siehe `custom_components/vesync/UPSTREAM.md`).
