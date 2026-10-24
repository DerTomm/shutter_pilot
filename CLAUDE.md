# CLAUDE.md – Arbeitsgrundlage & Fortschritts-Doku

Diese Datei führt Claude (Entwickler-KI) als eigene Projektdokumentation:
Funktionsumfang, Konventionen und ein fortlaufendes Fortschritts-Log. Sie wird
bei jedem größeren Arbeitsschritt aktualisiert und mit gepusht.

**Größenlimit:** CLAUDE.md wird bei jeder Session komplett in den Kontext
geladen, deshalb bewusst klein gehalten. Das Fortschritts-Log unten enthält
nur die **letzten fünf Einträge**; die vollständige Historie steht in
`docs/CHANGELOG_DEV.md`. Beim Hinzufügen eines neuen Eintrags: den ältesten
der fünf hier herausnehmen und (unverändert) an den Anfang der Log-Einträge in
`docs/CHANGELOG_DEV.md` setzen, sonst wächst diese Datei wieder über das
Limit.

## Projekt

**Shutter Pilot** – Custom Integration für Home Assistant, die Rollläden nach
Zeit, Helligkeit oder Sonnenstand fährt. Konfiguriert wird nicht über
YAML oder Options-Flow, sondern über ein **eigenes Sidebar-Panel**.

- Repo: https://github.com/fschubi/shutter_pilot (Branch `master`)
- Verteilung über HACS · Mindestversion Home Assistant 2024.6.0
- `single_config_entry: true` – es gibt genau einen Config-Entry
- Sprache im Projekt: **Deutsch** (Commits, Changelog, Kommentare, Forumstexte).
  Code-Bezeichner und Docstrings im Python-Teil sind englisch.

## Aufbau

```
custom_components/shutter_pilot/
  __init__.py        Setup, Panel-Registrierung, WebSocket-API, Minutentakt
  const.py           Alle Config-Keys, Defaults, Events – die Referenz
  helpers.py         Herzstück: Beschattungslogik, Positionen, Sperren (~980 Z.)
  scheduler.py       Zeit- und Sonnenmodus: Fahrten planen und auslösen
  brightness.py      Helligkeitsmodus mit erlaubten Zeitfenstern
  elevation.py       Beschattung: Elevation, Azimut, Bedingungen, pro Rollladen
  ventilation.py     Automatisches Lüften nach Bedingungen
  awning_guard.py    Markisen: Wind-, Regen- und Frostschutz (Sperre + Zwangsfahrt)
  awning_dusk.py     Markisen: bei Dämmerung einfahren, nie automatisch wieder aus
  schedule_times.py  Zeitmathematik: Wochenende, Jitter, Zeitklammern
  window_trigger.py  Reaktion auf Fensterkontakte
  window_helper.py   Fensterzustand und Aussperrschutz
  cover_tracker.py   Positionen mitschreiben, nach Neustart wiederherstellen
  cover_verify.py    Fahrtkontrolle: erreicht der Rollladen die Position?
  position_store.py  JSON-Speicher der letzten Positionen
  weather_data.py    Tagesvorhersage über weather.get_forecasts
  group_actions.py   Folgeaktion Licht je Bereich
  switch/sensor/binary_sensor.py   Entitäten
  services.py        Dienste (Gruppenaktionen)
  frontend/shutter-pilot-panel.js  Das komplette Panel (~4800 Z., ein File)
tests/               pytest-Suite (871 Tests)
tests/panel/         Panel in Node rendern – laeuft in der CI mit
```

## Funktionsumfang

### Bereiche und Modi

Ein **Bereich** bündelt Rollläden und legt fest, *wann* gefahren wird. Jeder
Rollladen hat einen Bereich fürs Hochfahren und einen fürs Runterfahren – die
dürfen verschieden sein (morgens raumweise, abends alle zusammen).

| Modus | Auslöser |
| --- | --- |
| `time` | feste Uhrzeiten, getrennt für Woche und Wochenende |
| `brightness` | Helligkeitssensor mit Schwellen, nur in erlaubten Zeitfenstern |
| `sun` | Sonnenauf-/-untergang plus Offset, optional in Zeitklammern |
| `none` | gar nichts – nur Beschattung und Lüften (2.16.0) |

Zwei Sperren je Bereich unterbinden das **Hochfahren** ganz (Runterfahren und
Beschattung laufen weiter): ein Wochenendhaken, der an `is_weekend_schedule()`
hängt und damit auch Feiertage und Ferien erfasst, und der Bedingungs-Slot
`no_up` – ausgewertet über `_own_slot_met()`, also „nicht gesetzt = nein, toter
Sensor = nein". Beide fragt `automated_up_blocked()` an genau zwei Stellen ab:
`scheduler._run_up_async` und `brightness._run_up`.

Wochenendwerte fallen immer auf die Wochentagswerte zurück, wenn sie leer
bleiben. Statt Samstag/Sonntag kann ein **Workday-Sensor** entscheiden
(Feiertage, Schichtdienst). Eine **Präsenzsimulation** streut die Zeiten um bis
zu N Minuten; der Wert ist pro Tag stabil, nicht pro Fahrt.

### Rollläden

Je Rollladen: Positionen für offen, geschlossen und Sonnenschutz, optional eine
**abweichende Schließposition** für laue Abende und eine **Frostposition**,
optional **Lamellenwinkel** (Raffstore). Fenstersensor mit Aussperrschutz, dazu
optional ein **zweiter Fensterkontakt** (Doppelflügel, ODER-verknüpft, der
offenere gewinnt) und ein zweiter Kontakt, wenn „gekippt" als eigene Entität
gemeldet wird (der behält Vorrang und wird *nicht* mitgerankt – er ist ein
Modifikator, kein zweiter Flügel),
und eine **Entprellung** (0–30 s), bevor auf „geschlossen" reagiert wird.
Optional fährt eine vorgemerkte Nachholfahrt schon jetzt auf die
Lüftungsposition (`window_vent_while_open`, Vorgabe aus) – ohne den Haken
passiert bei offenem Fenster gar nichts.
Zwei weitere Haken (2.24.0, beide ohne Migration): `window_react` (Vorgabe an;
aus = der Kontakt bewegt nichts, hält nur automatische Fahrten zurück) und
`drive_after_close_up` (Vorgabe aus; hält auch die **Hochfahrt** zurück –
bewusst nicht unter `drive_after_close`, das würde bestehenden Nutzern die
Morgenfahrt nehmen).

An einem Antrieb ohne Positionierung gibt es eine dritte Stellung: die am Motor
angelernte **„My"-Position** (`my_position_entity` + `my_position_pct`, RTS über
Overkiz als `button.*`). `my_position_target()` greift **nur im Rückfallzweig**
von `_send_position()`; wo Positionen gehen, ist die Zahl die genauere
Anweisung.

### Beschattung

Aktiv, wenn **alle** Bedingungen zugleich gelten:

1. Sonnenhöhe im konfigurierten Bereich (min/max)
2. Sonne steht vor den Fenstern (Azimut, Kompass-Schnellwahl)
3. bis zu **vier Zusatzbedingungen** – Binärsensor, Zahlenwert mit Ein-/
   Ausschaltschwelle oder Textzustand (Wetterlage). Dieselbe Mechanik trägt die
   eigenen Slots `close`, `frost` und `vent_a`/`vent_b` – die sind aber **fail
   closed**, ein toter Sensor löst dort nichts aus.
4. Datum liegt im konfigurierten **Beschattungszeitraum** (Jahreswechsel möglich)
5. Uhrzeit liegt im **Beschattungs-Zeitfenster** (`shade_from`/`shade_to`, beide
   einzeln optional, je Bereich und je Rollladen). Die einzige der fünf
   Prüfungen, die nicht die Sonne beschreibt, sondern den Haushalt – und
   bewusst **ohne** Wrap über Mitternacht

Dazu drei Einstellungen, die nicht die Sonne beschreiben, sondern das
Verhalten – alle je Bereich, alle mit Vorgabe „wie bisher":

* **Sonnenschutz-Schalter** (`switch.shutter_pilot_sonnenschutz_<bereich>`),
  getrennt vom Automatik-Schalter. Ausschalten *gibt frei*, es friert nicht ein.
* **Am Ende des Beschattungstags öffnen** – sonst steht der Rollladen bei
  `elev < e_min` bis zum Abendplan auf Beschattungshöhe. Im Sonnenmodus sind
  das Minuten, sonst Stunden.
* **Nur beschatten, was schon offen ist** – `set_cover_position(50)` ist von
  unten derselbe Befehl wie von oben; die Richtung steht nur in der aktuellen
  Position.

Die Beschattungsposition ist nicht eine Zahl, sondern drei Quellen, spezifisch
zuerst: eine **Entität** (0–100, unlesbar = Rückfall statt Aussetzer), eine
**zweite feste Position** hinter dem Slot `sp_alt` (Bedingung am Bereich,
Position am Rollladen – das Paar von `closed_alt`), sonst die normale. Sie
greift **sofort**, auch mitten in einer laufenden Beschattung; `_shade_pos_last`
verhindert dabei, dass der Motor jede Minute ein Prozent nachfährt. Ein
Rollladen kann über `shading_enabled` ganz aussteigen – anders als der
Automatik-Schalter hält das nur die Beschattung an, nicht den Zeitplan.

Geometrie und Bedingungen lassen sich **pro Rollladen** überschreiben. Der
Rückfall wirkt je Bedingungs-Slot: gesetzt am Rollladen ersetzt den Slot,
leer erbt den Bereichswert. Die Hysterese liegt deshalb pro Cover, nicht pro
Bereich – sonst hebt eine Wolke vor einem Fenster die Beschattung des anderen
auf. Ein fehlender oder toter Sensor blockiert nie (fail open).

### Markisen

Ein Eintrag in derselben `shutters`-Liste, unterschieden durch `device_kind`
(fehlt = Rollladen, keine Migration). Der Fahrweg ist **derselbe**: die
Beschattung fährt auf `position_sun_protect` und gibt auf `position_open` frei,
und welche Zahl das ist, entscheidet die Konfiguration – bei der Markise 100
bzw. 0. Nur die *Rückfallwerte* in `get_position_for_role()` drehen sich.

Anders sind zwei Dinge:

1. **Kein Zeitplan.** Scheduler, Helligkeit, Lüften und Fenstertrigger filtern
   Markisen aus (`only_shutters()`), der Aussperrschutz steigt früh aus – er
   klemmt nach unten, und unten ist bei einer Markise die *sichere* Seite.
2. **`awning_guard.py`.** Wind, Regen, Frost global unter Einstellungen; **nur
   der Wind** ist je Markise überschreibbar (örtlich verschieden), Regen und
   Frost fallen übers ganze Haus gleich. Slots derselben Mechanik, mit
   der Bedeutung **„Gefahr liegt vor"** statt „Bedingung erfüllt" – dadurch
   passen Binärsensor, Zahlenhysterese und Textzustände ohne eine einzige
   Änderung an `_condition_slot_met()`. Dazu eine **Sperrzeit** je Slot, die
   die Wertehysterese nicht leisten kann (eine Bö ist nach 20 s vorbei).

Optional: **Ausfahrlänge nach Sonnenhöhe**, zwei Stützpunkte linear
interpoliert, mit Mindeständerung gegen den Minutentakt am Getriebe.

Optional (2.22.0): **`awning_dusk.py`**, bei Dämmerung einfahren. Eigener
Bedingungs-Slot je Markise (`AWNING_DUSK_SLOT`), unabhängig vom
Sonnenschutz-Schalter des Bereichs und unabhängig vom Wetterschutz. Anders
als `awning_guard.py` respektiert er Hauptschalter, Bereichsautomatik und die
Automatik der Markise – eine Komfortfunktion, keine Sicherheitsfunktion, und
deshalb bewusst kein vierter Guard-Slot neben Wind/Regen/Eis. Fährt nur
**einmal ein**, wenn die Bedingung eintritt; die Freigabe (Bedingung fällt
weg) löst **keine** Fahrt aus – ausfahren bleibt Sache der Beschattung
(falls eingeschaltet) oder von Hand. Der Speicher hängt am Cover
(`condition_memory(data, "dusk", cover)`), nicht an einer Bereichs-ID, sonst
würden Markisen ohne echten Bereich in denselben Hysterese-Topf fallen.

### Manuelle Übersteuerung

Drei Modi je Bereich: `never` (manuelle Position blockiert bis zum nächsten
Schließen), `daily` (gilt nur am selben Tag), `next_action` (Automatik gewinnt
immer). Dafür trennt die Integration eigene Fahrten von fremden – über
Pending-Marker und ein Zeitfenster („recent automation").

### Fahrtkontrolle

Optional: nach jeder automatischen Fahrt prüfen, ob die Position tatsächlich
erreicht wurde, sonst wiederholen. Am Ende wird der gespeicherte Wert
korrigiert und `shutter_pilot_cover_failed` gefeuert. Rollläden ohne
Positionsmeldung werden übersprungen. Einstellbar: Wartezeit, Toleranz,
Wiederholungen.

### Weiteres

- **Positionsspeicher**: letzte Positionen überleben den Neustart; beim Start
  wird korrigiert, wenn die Cover-Integration falsch wiederhergestellt hat.
- **Wetter**: eigene Tagesvorhersage über `weather.get_forecasts`, ausgegeben
  als drei Sensoren (Höchst-, Tiefsttemperatur, Wetterlage) – direkt als
  Bedingung nutzbar.
- **Frostschutz**: eigener Bedingungs-Slot, der **nach unten** vergleicht, plus
  Rolle `closed_frost`. Gewinnt gegen die abweichende Schließposition.
- **Automatisches Lüften**: eigener Bedingungs-Slot je Bereich. Rangfolge
  Fensterkontakt > Beschattung > Lüften; zurück auf die vorherige Position.
- **Licht-Folgeaktion** je Bereich beim Runterfahren.
- **Minutentakt**: ein einziger `async_track_time_change` versorgt Scheduler,
  Wetter, Beschattung und Lüften – nicht pro Modul einen eigenen Timer anlegen.

### Entitäten, Dienste, Events

| Art | Entität |
| --- | --- |
| Schalter | `switch.shutter_pilot_system` (Hauptschalter), je Bereich und je Rollladen ein Auto-Schalter, je Bereich mit Beschattung ein Sonnenschutz-Schalter |
| Sensor | je Bereich „nächste Fahrt"; **einer fürs ganze Haus** (`shutter_pilot_status`: offen/geschlossen/teilweise, dazu Zahlen je Gruppe und die beschatteten Bereiche); Vorhersage Höchst-/Tiefsttemperatur und Wetterlage nur, wenn eine Wetter-Entität hinterlegt ist |
| Binärsensor | je Bereich „Sonnenschutz aktiv"; je Markise „Sperre" mit Grund und Restzeit |

Dienste: `open_group`, `close_group`, `sun_protect_group`, `ventilate_group`,
`stop_group`, `retract_awnings`, `resume_automation`. **Bereich überall
optional** – ohne ihn gelten sie fürs ganze Haus.
Events: `shutter_pilot_cover_moved`, `shutter_pilot_cover_failed`,
`shutter_pilot_awning_retracted`.

### Panel

Ein einzelnes JS-File, kein Build-Schritt. Tabs: Dashboard · Bereiche ·
Rollläden · Markisen · Dachfenster · Einstellungen. Besonderheiten, die man kennen muss:

- **LitElement kommt aus der Prototypenkette** eines geladenen HA-Elements –
  Home Assistant stellt kein Modul dafür bereit. Der Resolver probiert zehn
  Kandidaten und läuft an Mixins vorbei; findet er nichts, zeigt das Panel eine
  Meldung statt einer weißen Seite. `render()` liegt in einem try/catch.
- **macOS-App (Mac Catalyst)**: native `<input type="time">` und `<select>`
  sind dort kaputt (Absturz bzw. öffnet nicht). `NATIVE_PICKERS_BROKEN`
  erkennt die Plattform, dann werden eigene Bedienelemente gerendert.
- **Rechte**: Ohne Administrator zeigt das Panel nur das Dashboard mit den
  Bedienknöpfen. Das ist Bequemlichkeit – die Grenze liegt auf dem Server.
- **Über den Bereichskarten steht ein Block fürs ganze Haus** (2.18.0): dieselben
  fünf Fahrknöpfe für alle Rollläden, Automatik und Beschattung für alle Bereiche,
  dazu Sonnenauf-/-untergang, Elevation, Azimut und die Tagesvorhersage. Die
  Schalter laufen über die WebSocket-Befehle und sind deshalb Admin-only, die
  Fahrknöpfe nicht – dieselbe Trennung wie auf den Karten.
- **Die Bedienknöpfe rufen die `cover`-Dienste direkt auf** (damit HA die Rechte
  je Entität prüft). Sie kommen damit an *jedem* Riegel im Backend vorbei.
  Dreimal doppelt gebaut: Mindestabstand, Markisensperre, Aussperrschutz. Bei
  einem neuen Riegel ist die erste Frage, ob das Panel ihn kennt. Trennung:
  **Gruppenknopf = Bereich handelt** (Rollladenschalter gilt), **Zeilenknopf und
  Dienste = von Hand** (gilt nicht – sonst ist ein reparierter Antrieb nicht
  prüfbar).
- **i18n**: 11 Sprachen (de, en, fr, es, it, nl, da, sv, pl, pt, nb) im Objekt
  `I18N`. Jeder neue sichtbare Text braucht einen Schlüssel in **allen** elf;
  `t()` fällt sonst auf Englisch zurück. Seit 2.7.1 sind alle elf **vollständig**
  (Stand 2.23.0: je 446 Schlüssel) – das gilt es zu halten. Prüfskript: alle
  Sprachmengen gegen `de` halten, ist in zwanzig Zeilen geschrieben.

### WebSocket-API

| Befehl | Rechte |
| --- | --- |
| `shutter_pilot/get_status` | alle (lesend) |
| `save_area`, `delete_area`, `save_shutter`, `delete_shutter` | **Admin** |
| `save_settings`, `set_master_enabled`, `set_auto_mode`, `set_shutter_automation`, `set_sun_protect` | **Admin** |

Alle ändernden Befehle tragen `@websocket_api.require_admin` (außen, darunter
`websocket_command` – Reihenfolge wie in HA Core). Kommt ein neuer schreibender
Befehl dazu: **nicht vergessen**.

## Konventionen

- Kommentare erklären **warum**, nicht was. Keine Doppelung des Codes.
- Neue Config-Keys immer in `const.py`, mit Default daneben.
- Panel und Backend gehören zusammen: neues Feld → Key, Panel-Feld, i18n×11,
  Test, README (beide Sprachen), Changelog.
- Tests für jede Logikänderung. Die Suite ist die Absicherung gegen Regressionen
  in einer Integration, die niemand hier im Wohnzimmer nachstellen kann.
- Commit-Nachrichten deutsch, Fließtext statt Stichpunktliste, mit Begründung.

## Entwicklung

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest            # 871 Tests, ~21 s
```

`.venv/` ist in `.gitignore`. In `pytest.ini` steht `-q` schon in `addopts` –
ein zusätzliches `-q` ergibt `-qq` und verschluckt die Zusammenfassung, also
ohne Argument aufrufen. Die CI ([tests.yaml](.github/workflows/tests.yaml))
fährt dieselbe Suite bei jedem Push auf `master` mit Python 3.13.

**Panel testen ohne Home Assistant:** Das JS lässt sich in Node mit einem
Stub für `customElements`/LitElement auswerten und rendern. Seit 2.21.1 liegt
das **im Repo** (`tests/panel/`, angebunden über `tests/test_panel.py`) und
läuft in der CI mit – vorher war es Wegwerf-Werkzeug im Scratchpad, und genau
deshalb ging ein ReferenceError raus, den es gefunden hätte. Der Renderer
deckt alle Ansichten, alle Formulare und alle Bereichsmodi ab, **mit zwei
Einträgen je Geräteart**: der Kopierknopf wird erst ab dem zweiten gerendert.

## Release

1. `manifest.json` Version hochziehen, `CHANGELOG.md` ergänzen
2. committen, `git push origin master`, CI grün abwarten
3. `git tag -a vX.Y.Z -m "…"` + `git push origin vX.Y.Z`
4. `gh release create vX.Y.Z --title "…" --notes-file …`

**Ohne GitHub-Release zieht HACS die Version nicht.** Die Release-Notes sind
für Endnutzer geschrieben (Emoji-Überschriften, Tabellen, „was ändert sich für
mich"), nicht als Commit-Log.

## Projektstand

Version **2.24.0**, im Forum aktiv genutzt. Seit 18.10.2026 im
**HACS-Default-Store** (PR [hacs/default#9592](https://github.com/hacs/default/pull/9592), von frenck gemergt).

## Fortschritts-Log

Vollständige Historie (ältere Einträge) steht in `docs/CHANGELOG_DEV.md` – hier nur die letzten fünf, damit diese Datei nicht wieder über das Kontextlimit wächst. Neuer Eintrag kommt hier dazu; wird die Liste hier zu lang, wandert der älteste nach `docs/CHANGELOG_DEV.md`.

### 2026-10-24 – 2.24.0: die Tür als Riegel, nicht als Antrieb (Raffstore, Stufe 1)

Florian (simon42 #191/#193) und Claus (#196, #202): eine Terrassentür mit
Raffstore soll nichts bewegen, nur automatische Fahrten zurückhalten und nach
dem Schließen nachholen. Der Gesamtplan steht in `docs/PLAN_RAFFSTORE.md`
(sieben Stufen); das hier ist Stufe 1.

**Zwei neue Haken, beide ohne Migration** (`shutter.get(KEY, Default)`):
`window_react` (Vorgabe **an**) – aus: `window_trigger` überspringt "offen/
gekippt", der Zweig "geschlossen" (Nachholfahrt, Wiederherstellung) bleibt;
`drive_after_close_up` (Vorgabe **aus**) – die Hochfahrt (`scheduler.
drive_shutters`, `brightness._run_up`) wird bei offenem Fenster mit
`remember_drive_after_close` vorgemerkt, samt Lamellenwinkel.

**Warum ein eigener Haken statt `drive_after_close` zu erweitern:** wer den
gesetzt hat, fährt morgens bei offenem Fenster heute hoch; eine Erweiterung
hätte ihm die Morgenfahrt genommen. Eigener Test hält das fest. Die Vormerkung
steht **nach** `should_skip_automated_up`, sonst merkte sich ein ohnehin
gehaltener Rollladen eine Fahrt vor; `covers_driven_up/down` werden
spiegelbildlich zum Runter-Zweig gepflegt. Beide Schlüssel stehen auch in
`AWNING_UNUSED_KEYS`/`WINDOW_UNUSED_KEYS` (const.py und Panel).

**Nicht angefasst, mit Absicht:** `has_guard()`/`GUARDED_KINDS` (rund 15
Stellen, u. a. hebt `window_helper` den Aussperrschutz für diese Arten auf)
und der Gerätetyp – Raffstore bleibt ein Rollladen mit Lamellen. Der
Windschutz (Stufe 2) bekommt ein eigenes Prädikat mit eigener Sturmposition.

**Verifiziert:** `pytest` 871 grün (9 neue in `tests/test_door_lock_raffstore.py`,
1 in `tests/test_panel.py`). Gegenproben je Datei: ohne `window_trigger` fallen
2, ohne `scheduler` 1, ohne `brightness` 1. Kontrollfälle ohne Haken und mit
nur `drive_after_close` fahren wie bisher. i18n 4 neue Schlüssel ×11.
**Nicht im Browser und nicht im echten Home Assistant geprüft** – Florian soll
es testen.

### 2026-10-24 – 2.23.5: die Startmeldung, die die Wiederherstellung blind machte

mag2000 (simon42 #201): abends zugefahren, Home Assistant neu gestartet,
danach fahren alle Rollläden hoch. Beim Gegenlesen der Startlogik zeigte
sich, dass Shutter Pilot nicht hochfährt – die Cover stehen nach dem Start
auf der Standardposition der Cover-Integration, und die Wiederherstellung,
die sie zurückholen soll, sah nichts zu tun.

**Ursache, nachgestellt:** `ShutterPositionStore.async_load()` gibt dasselbe
Dict zurück, das der Tracker beschreibt. Meldet ein Cover nach dem Start
zuerst 100 % (`unavailable` → Standardwert, `old_position` ist `None`), bucht
der Tracker das als Handfahrt, schreibt `100/manual` in genau dieses Dict und
ruft `note_manual_position` (→ „oben"). Die Wiederherstellung liest ihre
Datensätze erst nach 5 s und vergleicht dann 100 mit 100. Dazu stand der
Rollladen danach in `covers_driven_up`, der nächste Morgen hätte ihn
übersprungen.

**Fix (2 Dateien):** der Speicher merkt sich beim ersten Laden den Stand von
der Platte (`get_loaded_snapshot()`), die Wiederherstellung liest den, und
nach einer Rückfahrt bucht `note_manual_position` die Endlage richtig um
(unten statt oben). Das Verhalten bei übereinstimmender Meldung ist
unverändert (eigener Test).

**Offen / Risiko:** ob das mag2000s Ursache ist, ist nicht bestätigt – seine
Cover-Art und das Log (`Startup restore`) fehlen. Die Wiederherstellung fährt
jetzt in Fällen zurück, in denen sie vorher durch das Überschreiben blind war:
ein Rollladen, der während der Neustartlücke von Hand bewegt wurde, geht auf
die gespeicherte Position zurück; ein Neustart mitten in einer Fahrt kann auf
die Zwischenposition zurückfahren. Beides kurze Zeitfenster, aber ein
Verhaltenswechsel.

**Verifiziert:** `pytest` 861 grün (3 neue, `tests/test_startup_restore_race.py`).
Gegenprobe: Fix entschärft → genau die zwei Fix-Tests fallen, der Test
„übereinstimmende Meldung" bleibt grün. Nicht in echtem Home Assistant geprüft.

### 2026-10-18 – 2.23.4: im offiziellen HACS-Store

frenck hat hacs/default#9592 freigegeben und gemergt. Seine Begründung für
die Freigabe: die schreibenden WebSocket-Befehle sind admin-only, das Panel
für Nicht-Admins offen zu lassen ist in Ordnung (die Grenze liegt auf dem
Server).

**Sein Hinweis, nachgeprüft und behoben:** `ShutterPilotOptionsFlow` las
`self.config_entry`, das HA erst ab 2024.11 selbst setzt – `hacs.json` sagt
2024.6.0. Jetzt wird der Eintrag im Konstruktor übergeben und als
`self._entry` gehalten. **Nicht** `self.config_entry` zuweisen: ab 2024.11
veraltet, später ein Fehler. Neuer Test `tests/test_options_flow.py` (2):
einmal über `hass.config_entries.options`, einmal ohne gebundenen Handler –
der simuliert < 2024.11. Gegenprobe mit altem Code: genau der zweite fällt.

**README (beide Sprachen) und FORUM_POST.md:** Installation ohne
benutzerdefiniertes Repository, Badge HACS-Default, My-HA-Link. Abgleich mit
dem Funktionsumfang: „drei Modi" und „bis zu zwei Bedingungen" waren
veraltet; neu sind Abschnitte zur manuellen Übersteuerung (nur
Zwischenpositionen, nur das Hochfahren – `should_skip_automated_up`), zum
Neustart (Abweichung > 8 % → zurückfahren, `POSITION_TOLERANCE_PCT`) und
zum Export unter Fehlersuche.

**Verifiziert:** `pytest` 858 grün. Nicht in einer HA < 2024.11 geprüft –
nur über den Test ohne Handler.

### 2026-10-12 – 2.23.3: die 0, die keine leere Grenze ist

Eine Forumsmeldung (Linos, simon42 #185): Hochfahren ab 06:30 Uhr und mehr
als 20 lx; die Helligkeit war seit 07:19 da, die Rollläden fuhren erst um
ca. 07:30. Er vermutete die „wiederholte Bestätigung" (`lux_hold`).

**Kein Codefehler, nachgerechnet bis zur Ursache.** Sein Export: `lux_hold`
leer, „spätestens hoch" aus, aber in allen fünf Bereichen
`b_up_before_sunrise = 0`. `_sun_bound_ok()` (brightness.py) unterscheidet
leer (keine Grenze) von `0` (nicht vor Sonnenaufgang) – das war immer so und
steht im README. Sonnenaufgang am 12.10. in Siegenburg: 07:28 (astral);
sein Sensor meldet alle 2–3 Minuten, die erste Meldung nach 07:28 fuhr.
„zuletzt geladen vor 1453 min" schloss den Montagsneustart aus.

**Änderung nur im Panel:** unter den „Zusätzlichen Sonnengrenzen" steht jetzt
dauerhaft „Leer = keine Grenze. Eine 0 ist eine Grenze …"
(`f_sunbound_empty`), und eine gelbe Warnung (`f_sunbound_zero`) erscheint,
sobald eines der beiden Felder explizit `0` enthält. Dafür löst `numOpt`
bei `change` ein `requestUpdate()` aus. i18n 448/448 ×11. **Merke:** eine
Einstellung, bei der „0" und „leer" verschiedene Dinge sind, ist ohne
sichtbaren Hinweis eine Falle – dasselbe Muster wie der unsichtbare
Rollladen-Override (heinzie, 2.23.1).

**Verifiziert:** `pytest` grün (neuer Test in `tests/test_panel.py` prüft
Schlüssel und Warnzeile im Panel). Nicht im Browser geprüft.

### 2026-10-04 – 2.23.2: das Fenster, das den geparkten Rollladen nicht kannte

Zwei Meldungen, ein Release. Bjoerg (smarthome #166), Export mit
Nachträgen vom 30.9.–4.10., und Nils (simon42 #183, keine Codeänderung).

**Fund 1 (Bjoerg, echter Fehler, nachgestellt): nach der Abendfahrt bei
offenem Fenster reagierte „offen → gekippt" nicht.** Die Abendfahrt
(`brightness._run_down`, `window_vent_while_open`) parkt den Rollladen auf
95 % und merkt die Vollfahrt vor, startet aber keinen Fenstertrigger-Zyklus.
Die Richtungsprüfung in `window_trigger.py` (soll tagsüber verhindern, dass
ein Fenster einen offenen Rollladen herunterzieht) hielt ihn für offen: Ziel
30 < 95, nicht geschlossen, kein Zyklus → `continue`. Nach „zu" und wieder
„auf" lief ein Zyklus, danach ging gekippt – exakt sein Protokoll. Fix:
`waiting_for_window` (Nachholfahrt vorgemerkt **und** `window_vent_while_open`)
zählt wie ein aktiver Zyklus. Ohne den Haken bleibt es beim Stehenbleiben.

**Fund 2 (Bjoerg, Mechanismus nachgestellt, sein Fall nicht bewiesen):
Schlafzimmer morgens bei 30 %, Quelle „manual", blockiert das Hochfahren.**
`cover_tracker` hielt eigene Fahrten nur 90 s als Automatik fest; jede
spätere abweichende Positionsmeldung (31 statt 30, langsamer Antrieb,
Reload) wurde als Handfahrt gebucht – Quelle `manual` und
`forget_window_cycle`. Fix: Meldung innerhalb 3 % um das zuletzt gesendete Ziel
(`commanded_position`) bleibt Automatik. Eine echte Handfahrt ist weiter
manuell (eigener Test). **Offen:** sein Debug-Log (`Position saved (manual)`)
würde zeigen, ob es wirklich dieser Weg war. Der Fall „Griff während der
Fahrt zurück auf Auf, bleibt bei 30 %" ließ sich im Code nicht nachstellen
(mit aktivem Zyklus kommt der Befehl 95 %) – vermutlich Folge von Fund 2 oder
des Antriebs.

**Nils (simon42 #183, keine Codeänderung):** zweistufiges Schließen (10 Lux →
60 %, 22 Uhr → ganz zu) gibt es nicht; der Helligkeitsmodus fährt je Dunkel-
Episode einmal. Der Rat „zwei Bereiche" geht nicht (ein Runter-Bereich je
Rollladen, doppelter Cover wird abgelehnt). Umweg nur gelesen, nicht
getestet: Zeitmodus 22:00 + Beschattung mit invertierter Lux-Bedingung,
Zeitfenster, Position 60. Funktionswunsch notiert.

**Verifiziert:** `pytest` 855 Tests grün (5 neue,
`tests/test_window_parked_and_late_report.py`). Gegenprobe: Fixes entschärft →
genau die zwei Fix-Tests fielen. Nicht im Browser geprüft – reine
Backend-Logik.

## graphify

This project has a knowledge graph at `graphify-out/` with god nodes,
community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when
  `graphify-out/graph.json` exists. Use `graphify path "<A>" "<B>"` for
  relationships and `graphify explain "<concept>"` for focused concepts.
  These return a scoped subgraph, usually much smaller than
  `GRAPH_REPORT.md` or raw grep output.
- If `graphify-out/wiki/index.md` exists, use it for broad navigation instead
  of raw source browsing.
- Read `graphify-out/GRAPH_REPORT.md` only for broad architecture review or
  when `query`/`path`/`explain` do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current
  (AST-only, no API cost).
