"""Von Hand auf eine Zwischenposition gehoben: die naechste Dunkel-Episode
faehrt wieder zu (Claus, community.simon42.com/90112/207).

Seine Diele: Helligkeitsmodus, ein Template-Sensor meldet 0 lx, solange das
Licht an ist. 16:05 Licht an -> Abendfahrt (Sichtschutz), 16:06 Licht aus und
der Raffstore von Hand auf 98 % - das ist weder "auf" (50 %) noch "zu", also
eine Zwischenposition. `note_manual_position()` liess den Unten-Merker stehen,
und `_run_down` ueberspringt jeden Rollladen darin; die echte Daemmerung um
17:19 fuhr deshalb nicht mehr zu.

Jetzt faellt der Unten-Merker bei einer Zwischenposition. Damit eine Handfahrt
im Dunkeln nicht sofort wieder zugefahren wird, merkt sich jede Handfahrt ihren
Zeitpunkt, und `_run_down` fasst einen Rollladen in der laufenden
Dunkel-Episode nach einer Handfahrt nicht mehr an - erst in der naechsten."""

from __future__ import annotations

from custom_components.shutter_pilot.const import (
    CONF_AREA_BRIGHTNESS_DOWN_THRESHOLD,
    CONF_AREA_BRIGHTNESS_UP_THRESHOLD,
    CONF_POSITION_CLOSED,
    CONF_POSITION_OPEN,
)
from custom_components.shutter_pilot.helpers import note_manual_position

from tests.test_brightness_manual_reopen import (  # noqa: F401
    COVER,
    SHUTTER,
    _area,
    _drives,
    _lux,
    _setup,
    clock,
    drive,
)

DIELE = {**SHUTTER, CONF_POSITION_OPEN: 50, CONF_POSITION_CLOSED: 0}


def _diele_area():
    return _area(
        **{
            CONF_AREA_BRIGHTNESS_DOWN_THRESHOLD: 300,
            CONF_AREA_BRIGHTNESS_UP_THRESHOLD: 400,
        }
    )


async def test_claus_evening_runs_again_after_a_hand_lift(hass, drive, clock):
    _, data = await _setup(hass, _diele_area(), [DIELE])
    await _lux(hass, 0)  # Licht an, Sensor 0
    assert _drives(drive) == [(COVER, 0)]
    clock["t"] += 33
    await _lux(hass, 1000)  # Licht aus: die Episode ist vorbei
    clock["t"] += 30
    note_manual_position(data, DIELE, 98)  # Taster: von Hand hoch

    clock["t"] += 4000
    await _lux(hass, 10)  # die echte Daemmerung

    assert _drives(drive) == [(COVER, 0), (COVER, 0)]


async def test_a_hand_lift_in_the_same_episode_stays_lifted(hass, drive, clock):
    """Bestandsschutz: die Abendfahrt hat zugefahren, von Hand ein Stueck auf -
    die naechsten Meldungen im Dunkeln fahren ihn nicht wieder zu."""
    _, data = await _setup(hass, _diele_area(), [DIELE])
    await _lux(hass, 10)
    assert _drives(drive) == [(COVER, 0)]
    clock["t"] += 60
    note_manual_position(data, DIELE, 40)

    clock["t"] += 90
    await _lux(hass, 8)
    clock["t"] += 90
    await _lux(hass, 12)

    assert _drives(drive) == [(COVER, 0)]


async def test_closed_by_hand_then_lifted_in_the_dark_stays_lifted(
    hass, drive, clock
):
    """Der Fall, den ein blosses Loeschen des Unten-Merkers aufgemacht haette:
    von Hand zu (gebucht als "unten"), im Dunkeln von Hand ein Stueck auf -
    ohne Zeitpunkt fuhr die naechste Lux-Meldung ihn sofort wieder zu."""
    _, data = await _setup(hass, _diele_area(), [DIELE])
    note_manual_position(data, DIELE, 0)  # von Hand zu, vor dem Abend
    await _lux(hass, 10)  # Dunkel-Episode beginnt, der Merker haelt ihn
    assert _drives(drive) == []
    clock["t"] += 30
    note_manual_position(data, DIELE, 40)  # im Dunkeln ein Stueck auf

    clock["t"] += 60
    await _lux(hass, 8)

    assert _drives(drive) == []


async def test_without_a_hand_move_nothing_changes(hass, drive, clock):
    """Kontrolle: ohne Handfahrt fuehrt auch eine zweite Episode nicht doppelt
    aus, solange der Unten-Merker steht."""
    _, data = await _setup(hass, _diele_area(), [DIELE])
    await _lux(hass, 10)
    clock["t"] += 33
    await _lux(hass, 1000)
    clock["t"] += 4000
    await _lux(hass, 10)

    assert _drives(drive) == [(COVER, 0)]


async def test_the_export_names_what_the_manual_override_value_means(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.shutter_pilot.const import (
        CONF_AREAS,
        CONF_SHUTTERS,
        DOMAIN,
    )
    from custom_components.shutter_pilot.export import async_build_export

    hass.states.async_set("sensor.lichtsensor_garten", "5000")
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_AREAS: [_area(manual_override="never")],
            CONF_SHUTTERS: [DIELE],
        },
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {}).setdefault(
        entry.entry_id, {"master_enabled": True}
    )

    md = (await async_build_export(hass, entry))["markdown"]

    assert "| `manual_override` | never (Bis zur nächsten Schließfahrt) |" in md
