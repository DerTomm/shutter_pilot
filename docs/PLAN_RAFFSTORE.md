# Gesamtplan Raffstores

Stand 2026-10-21. Quelle: Forum simon42 #172 (Claus/Sancezz), #191/#193 (Florian/Fuchse), #196 (Claus).
Nichts davon ist umgesetzt. Erst nach Rückmeldung im Forum bauen.

## Leitplanken (gelten für jede Stufe)

1. **Bestandsschutz vor allem.** Jeder neue Schlüssel hat Vorgabe "wie bisher" und wird mit `shutter.get(KEY, Default)` gelesen. Keine Migration, keine Pflichtfelder.
2. **Raffstore bleibt ein Rollladen** (`device_kind` fehlt). Kein neuer Gerätetyp, kein eigener Tab: ein neuer `device_kind` würde von `only_shutters()` aus Zeitplan, Helligkeit und Fenstertrigger gefiltert (Falle aus `is_shutter()`). Die Raffstore-Einstellungen kommen als Abschnitt in das Rollladen-Formular, sichtbar bei `tilt_enabled`.
3. **`has_guard()` / `GUARDED_KINDS` nicht anfassen** (rund 15 Stellen, u. a. Aussperrschutz-Aufhebung in `window_helper.py:205`, Dienste, Export). Der Raffstore-Wind bekommt ein eigenes Prädikat.
4. **Die 858 vorhandenen Tests laufen unverändert grün.** Wird ein bestehender Test geändert, ist das ein Alarmsignal. Je Stufe neue Tests: ohne Schlüssel = altes Verhalten, mit Schlüssel = neues. Dazu eine Gegenprobe (Fix entschärfen, genau die neuen Tests fallen).
5. Je Feld: Key in `const.py`, Panel, i18n x11, Test, README (beide Sprachen), Export, Changelog. Neue Schlüssel in `AWNING_UNUSED_KEYS` / `WINDOW_UNUSED_KEYS` (const.py **und** Panel-JS) eintragen.
6. Release erst nach Freigabe. Stufen dürfen gebündelt werden.

## Stufe 1 – Tür als reiner Aussperrschutz (Florian)  — umgesetzt in 2.24.0 (lokal, noch nicht released)

| Schlüssel | Vorgabe | Wirkung |
| --- | --- | --- |
| `window_react` | an | Aus: Fenstertrigger fährt bei "offen/gekippt" nicht. Der Zweig "geschlossen" (Nachholfahrt, Wiederherstellen) bleibt. |
| `drive_after_close_up` | aus | Auf-Fahrten (Zeit, Helligkeit) bei offener Tür werden wie das Runterfahren vorgemerkt, samt Lamellenwinkel. |

Stolpersteine:
- **Nicht** unter dem bestehenden `drive_after_close` mitlaufen lassen: Nutzer mit diesem Haken würden morgens plötzlich nicht mehr hochfahren.
- Zurückhalten in `scheduler.py` (Aufruf mit `apply_lock_protection=False`) und `brightness._run_up` **nach** `should_skip_automated_up`, sonst wird ein ohnehin übersprungener Rollladen vorgemerkt.
- `covers_driven_up/down` spiegelbildlich zum Runter-Zweig pflegen (Fehlerklasse aus 2.22.4 und 2.23.0).
- Prüfen: Handfahrt löscht die Vormerkung weiterhin (`cover_tracker`).

## Stufe 2 – Windschutz für Raffstores (Florian, Claus)

| Schlüssel | Vorgabe | Wirkung |
| --- | --- | --- |
| `storm_guard` | aus | Opt-in je Raffstore |
| `storm_position` | 100 | Sturmposition |
| `storm_tilt` | 100 | Lamellen bei Sturm |
| Wind-Schwelle | wie global | je Raffstore überschreibbar (über `resolve_guard_config`), Sperrzeit 20 min |

Entschieden laut Forum: Sturm fährt hoch und **sperrt alle automatischen Fahrten** (Morgen, Abend, Beschattung) solange er anhält. Nachholen danach: keine Präferenz, Vorschlag: Sperre nur aufheben, kein Nachholen.

Stolpersteine:
- Nur der **Wind-Slot** (kein Regen/Frost, die hängen am Haus).
- Eigene zweite Schleife in `async_enforce_guard`, die Markisenschleife bleibt unverändert. Ruheposition = `storm_position`, **nicht** `position_open` (bei Raffstores unten).
- Sperre in Scheduler, Helligkeit und Beschattung abfragen, nur bei gesetztem Haken.
- **KNX-Windalarm am Aktor (Claus):** Ist der Aktor selbst verriegelt, soll Shutter Pilot nicht senden bzw. die Fahrtkontrolle das nicht als Fehler werten, und danach die zuletzt gewollte Stellung nachholen. Offen: wie erkennt man den Alarm (eigener Sensor?). Im Forum nachfragen.

## Stufe 3 – Position und Lamellen getrennt (Claus #172, #196, Kern seines Wunsches)

- Je Rolle (offen, zu, Sonnenschutz): Position **oder** Lamellen auf "unverändert" setzbar. Heute sendet `set_cover_position` immer eine Position, `get_tilt_for_role` kennt nur Zahlen oder `None` (= aus).
- Neue Werte "unverändert" dürfen bestehende Zahlen nicht umdeuten (leer = bisheriges Verhalten).
- Betroffen: `_send_position`, Fenster-/Vormerk-Pfad (Vormerkung muss "unverändert" speichern können), Fahrtkontrolle, "gilt als oben/unten"-Buchführung.
- **Reihenfolge Position -> Lamellen** (viele KNX-Aktoren setzen den Winkel nach einer Höhenfahrt zurück): heute werden beide nacheinander gesendet, ohne auf das Erreichen der Position zu warten. Optional: Winkel erst nach erreichter Position senden (Haken, Vorgabe aus).
- Die Entscheidung "Beschattung ist nicht eine Zahl, sondern drei Quellen" (CLAUDE.md) muss sauber weiterlaufen.

## Stufe 4 – Handbedienung nur an den Lamellen

- Heute vergleichen `cover_tracker` und `cover_verify` nur die Höhe. Eine reine Winkeländerung wird nicht als Handfahrt erkannt und nicht verifiziert.
- Erweiterung: Winkeländerung ohne Höhenänderung gegen das zuletzt befohlene Lamellenziel (mit Toleranz) als Handfahrt buchen, mit eigener Sperrzeit. Bestehende Fremdfahrt-Logik und das 3-%-Fenster (2.23.2) dürfen sich nicht ändern.
- Claus erkennt Tasten heute über `knx_event` und sperrt 1 h: Alternative wäre ein Dienst/Haken "Automatik pausieren für N min".

## Stufe 5 – Mehrstufiger Sonnenschutz (Claus)

- Mehrere Stufen mit Bedingungen, Rangfolge, Hysterese bzw. Haltezeit je Stufe (Wolken bei 2.000 lx), je Stufe Position/Lamellen fest oder "unverändert".
- Größter Brocken. Baut auf Stufe 3 auf. Bestehende Slot-Mechanik (`_condition_slot_met`, Hysterese pro Cover) wiederverwenden, nicht neu erfinden. Zusätzlich zur vorhandenen "zweiten Beschattungsposition" (`sp_alt`), die unverändert bleibt.

## Stufe 6 – Sichtschutz (Bad)

- Eigene Position/Lamellen, ausgelöst durch eine Entität (Badbelegung, Licht), **Vorrang vor Morgenfahrt und Beschattung**.
- Dazu "Hochfahren nur wenn Räume leer": passt auf den vorhandenen Slot `no_up` (nicht neu bauen, prüfen ob er reicht).

## Stufe 7 – Referenzfahrt

- Optional je Raffstore: einmal im Monat ganz hoch, dann runter, damit Position und Winkel stimmen. Eigener Haken, Vorgabe aus, im Minutentakt-Timer (kein eigener Timer).

## Außerhalb der Raffstores (Claus #172)

- **Notfall-Eingang** (Rauchmelder): alle Rollläden und Jalousien hoch, Automatik gesperrt solange aktiv. Eigene Funktion, hängt nicht an Raffstores. Als eigenen Funktionswunsch führen.

## Reihenfolge

1 -> 2 (kleine Pakete, lösen Floriansfall) -> 3 -> 4 (Grundlage für 5) -> 5 -> 6 -> 7. Notfall-Eingang separat einplanen.
Vorher im Forum klären: KNX-Windalarm (Stufe 2), Haltezeit/Stufen-Rangfolge (Stufe 5), Handbedienung (Stufe 4).
