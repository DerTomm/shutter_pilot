"""Tuer als reiner Aussperrschutz (Raffstore, simon42 #191 Florian, #196 Claus).

Zwei neue Haken, beide mit Vorgabe "wie bisher":

* `window_react` (Vorgabe an): aus = der Fensterkontakt bewegt nichts. Er
  bleibt Riegel fuer vorgemerkte Fahrten, faehrt aber nicht auf Lueftungs- oder
  Kippposition. Ein Raffstore, der tagsueber unten steht, zaehlt fuer den
  Trigger als "zu" und wurde bei jeder Tueroeffnung bewegt.
* `drive_after_close_up` (Vorgabe aus): die Hochfahrt bei offenem Fenster wird
  vorgemerkt und nach dem Schliessen nachgeholt, samt Lamellenwinkel. Bei einem
  Raffstore mit gleicher Auf- und Zu-Position ist "auf" nur ein Lamellenwechsel,
  der den Behang vor die offene Tuer fahren wuerde. Eigener Haken statt
  Erweiterung von `drive_after_close`: wer den schon gesetzt hat, faehrt morgens
  bei offenem Fenster heute hoch.

Die Kontrollfaelle ohne Haken sind der Bestandsschutz-Teil der Tests."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.shutter_pilot.brightness import setup_brightness_listener
from custom_components.shutter_pilot.const import (
    AREA_MODE_BRIGHTNESS,
    AREA_MODE_TIME,
    CONF_AREA_BRIGHTNESS_DOWN_THRESHOLD,
    CONF_AREA_BRIGHTNESS_SENSOR,
    CONF_AREA_BRIGHTNESS_UP_THRESHOLD,
    CONF_AREA_DOWN_ID,
    CONF_AREA_DRIVE_DELAY,
    CONF_AREA_ID,
    CONF_AREA_MODE,
    CONF_AREA_NAME,
    CONF_AREA_TIME_DOWN,
    CONF_AREA_TIME_UP,
    CONF_AREA_UP_ID,
    CONF_AREA_W_DOWN_FROM,
    CONF_AREA_W_DOWN_TO,
    CONF_AREA_W_UP_FROM,
    CONF_AREA_W_UP_TO,
    CONF_AREA_WE_DOWN_FROM,
    CONF_AREA_WE_DOWN_TO,
    CONF_AREA_WE_UP_FROM,
    CONF_AREA_WE_UP_TO,
    CONF_AREAS,
    CONF_COVER_ENTITY_ID,
    CONF_DRIVE_AFTER_CLOSE,
    CONF_DRIVE_AFTER_CLOSE_UP,
    CONF_NAME,
    CONF_POSITION_CLOSED,
    CONF_POSITION_OPEN,
    CONF_SHUTTERS,
    CONF_TILT_CLOSED,
    CONF_TILT_ENABLED,
    CONF_TILT_OPEN,
    CONF_WINDOW_CLOSE_DEBOUNCE,
    CONF_WINDOW_ENTITY_ID,
    CONF_WINDOW_OPEN_STATE,
    CONF_WINDOW_REACT,
    CONF_WINDOW_TILTED_STATE,
    DOMAIN,
)

COVER = "cover.raffstore_terrasse"
DOOR = "binary_sensor.terrassentuer"
SENSOR = "sensor.helligkeit"

AREA = {
    CONF_AREA_ID: "living",
    CONF_AREA_NAME: "Wohnbereich",
    CONF_AREA_MODE: AREA_MODE_TIME,
    CONF_AREA_TIME_UP: "07:00",
    CONF_AREA_TIME_DOWN: "19:00",
    CONF_AREA_DRIVE_DELAY: 0,
}


def _raffstore(**overrides) -> dict:
    """Auf und zu sind dieselbe Position, nur die Lamellen unterscheiden sich."""
    shutter = {
        CONF_COVER_ENTITY_ID: COVER,
        CONF_NAME: "Terrasse",
        CONF_AREA_UP_ID: "living",
        CONF_AREA_DOWN_ID: "living",
        CONF_POSITION_OPEN: 0,
        CONF_POSITION_CLOSED: 0,
        CONF_TILT_ENABLED: True,
        CONF_TILT_OPEN: 100,
        CONF_TILT_CLOSED: 60,
        CONF_WINDOW_ENTITY_ID: DOOR,
        CONF_WINDOW_OPEN_STATE: "on",
        CONF_WINDOW_TILTED_STATE: "none",
        CONF_WINDOW_CLOSE_DEBOUNCE: 0,
    }
    shutter.update(overrides)
    return shutter


@pytest.fixture
def calls(hass):
    return {
        "pos": async_mock_service(hass, "cover", "set_cover_position"),
        "tilt": async_mock_service(hass, "cover", "set_cover_tilt_position"),
    }


async def _setup(hass, shutter: dict, position: int = 0):
    hass.states.async_set(
        COVER, "open", {"current_position": position, "supported_features": 255}
    )
    hass.states.async_set(DOOR, "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Shutter Pilot",
        options={CONF_AREAS: [AREA], CONF_SHUTTERS: [shutter]},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.shutter_pilot._async_register_panel", return_value=None
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id]


async def _morning_tick(hass, data) -> None:
    """Der Scheduler um 07:00 des naechsten Tages (vermeidet das Vormarkieren
    beim Setup)."""
    when = (dt_util.now() + timedelta(days=1)).replace(
        hour=7, minute=0, second=0, microsecond=0
    )
    data["_minute_callbacks"]["scheduler"](when)
    await hass.async_block_till_done()


def _positions(calls_) -> list[float]:
    return [c.data["position"] for c in calls_["pos"]]


# --- Hochfahrt im Scheduler ---------------------------------------------------


class TestScheduledUpWaitsForTheDoor:
    async def test_the_up_drive_waits_and_runs_after_closing(self, hass, calls):
        _, data = await _setup(
            hass,
            _raffstore(**{CONF_DRIVE_AFTER_CLOSE_UP: True, CONF_WINDOW_REACT: False}),
        )
        hass.states.async_set(DOOR, "on")
        await hass.async_block_till_done()

        await _morning_tick(hass, data)

        assert calls["pos"] == [] and calls["tilt"] == []
        assert COVER in data["drive_after_close_pending"]
        assert COVER in data["covers_driven_up"]

        hass.states.async_set(DOOR, "off")
        await hass.async_block_till_done()

        assert _positions(calls) == [0]
        assert [c.data["tilt_position"] for c in calls["tilt"]] == [100]
        assert COVER not in data["drive_after_close_pending"]

    async def test_with_the_door_shut_it_drives_at_once(self, hass, calls):
        _, data = await _setup(hass, _raffstore(**{CONF_DRIVE_AFTER_CLOSE_UP: True}))

        await _morning_tick(hass, data)

        assert _positions(calls) == [0]

    async def test_without_the_hook_the_up_drive_goes_ahead(self, hass, calls):
        """Bestandsschutz: ohne den neuen Haken faehrt die Hochfahrt wie bisher."""
        _, data = await _setup(hass, _raffstore())
        hass.states.async_set(DOOR, "on")
        await hass.async_block_till_done()
        calls["pos"].clear()  # die Kontaktreaktion selbst ist nicht der Gegenstand

        await _morning_tick(hass, data)

        assert _positions(calls) == [0]
        assert COVER not in data["drive_after_close_pending"]

    async def test_drive_after_close_alone_does_not_hold_the_up_drive(
        self, hass, calls
    ):
        """Bestandsschutz: wer nur `drive_after_close` gesetzt hat, faehrt
        morgens bei offenem Fenster weiter hoch."""
        _, data = await _setup(hass, _raffstore(**{CONF_DRIVE_AFTER_CLOSE: True}))
        hass.states.async_set(DOOR, "on")
        await hass.async_block_till_done()
        calls["pos"].clear()

        await _morning_tick(hass, data)

        assert _positions(calls) == [0]


# --- Hochfahrt im Helligkeitsmodus -------------------------------------------


class TestBrightnessUpWaitsForTheDoor:
    @staticmethod
    async def _setup_brightness(hass, shutter: dict):
        area = {
            CONF_AREA_ID: "living",
            CONF_AREA_MODE: AREA_MODE_BRIGHTNESS,
            CONF_AREA_BRIGHTNESS_SENSOR: SENSOR,
            CONF_AREA_BRIGHTNESS_DOWN_THRESHOLD: 199,
            CONF_AREA_BRIGHTNESS_UP_THRESHOLD: 201,
            CONF_AREA_W_UP_FROM: "00:00", CONF_AREA_W_UP_TO: "23:59",
            CONF_AREA_W_DOWN_FROM: "00:00", CONF_AREA_W_DOWN_TO: "23:59",
            CONF_AREA_WE_UP_FROM: "00:00", CONF_AREA_WE_UP_TO: "23:59",
            CONF_AREA_WE_DOWN_FROM: "00:00", CONF_AREA_WE_DOWN_TO: "23:59",
        }
        hass.states.async_set(SENSOR, "50")
        hass.states.async_set(DOOR, "on")
        entry = MockConfigEntry(
            domain=DOMAIN,
            options={CONF_AREAS: [area], CONF_SHUTTERS: [shutter]},
        )
        entry.add_to_hass(hass)
        data = hass.data.setdefault(DOMAIN, {}).setdefault(
            entry.entry_id, {"master_enabled": True}
        )
        await setup_brightness_listener(hass, entry)
        return entry, data

    async def test_the_up_drive_is_remembered_not_driven(self, hass):
        with patch(
            "custom_components.shutter_pilot.brightness.set_cover_position",
            new=AsyncMock(return_value=True),
        ) as drive:
            _, data = await self._setup_brightness(
                hass, _raffstore(**{CONF_DRIVE_AFTER_CLOSE_UP: True})
            )
            hass.states.async_set(SENSOR, "5000")
            await hass.async_block_till_done()

        assert drive.await_count == 0
        pending = data["drive_after_close_pending"][COVER]
        assert pending["position"] == 0 and pending["tilt"] == 100
        assert COVER in data["covers_driven_up"]

    async def test_without_the_hook_it_drives_as_before(self, hass):
        with patch(
            "custom_components.shutter_pilot.brightness.set_cover_position",
            new=AsyncMock(return_value=True),
        ) as drive:
            _, data = await self._setup_brightness(hass, _raffstore())
            hass.states.async_set(SENSOR, "5000")
            await hass.async_block_till_done()

        assert drive.await_count == 1
        assert COVER not in data.get("drive_after_close_pending", {})


# --- Fenstertrigger -----------------------------------------------------------


class TestDoorContactStaysQuiet:
    async def test_react_off_moves_nothing_when_the_door_opens(self, hass, calls):
        await _setup(hass, _raffstore(**{CONF_WINDOW_REACT: False}), position=0)

        hass.states.async_set(DOOR, "on")
        await hass.async_block_till_done()

        assert calls["pos"] == [] and calls["tilt"] == []

    async def test_default_still_reacts(self, hass, calls):
        """Bestandsschutz: ohne den Schluessel bewegt der Kontakt wie bisher."""
        await _setup(hass, _raffstore(), position=0)

        hass.states.async_set(DOOR, "on")
        await hass.async_block_till_done()

        assert _positions(calls) == [50]

    async def test_react_off_still_runs_a_pending_drive_on_closing(
        self, hass, calls
    ):
        _, data = await _setup(
            hass,
            _raffstore(**{CONF_WINDOW_REACT: False, CONF_DRIVE_AFTER_CLOSE: True}),
            position=0,
        )
        hass.states.async_set(DOOR, "on")
        await hass.async_block_till_done()
        await _morning_tick(hass, data)  # nichts zu fahren, Tuer offen
        from custom_components.shutter_pilot.helpers import (
            remember_drive_after_close,
        )

        entry = hass.config_entries.async_entries(DOMAIN)[0]
        remember_drive_after_close(
            hass, entry, data, COVER, position=30, tilt=None, reason="Test",
            shutter=entry.options[CONF_SHUTTERS][0],
        )

        hass.states.async_set(DOOR, "off")
        await hass.async_block_till_done()

        assert 30 in _positions(calls)
