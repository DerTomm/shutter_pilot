"""Hoehe und Lamellen getrennt (simon42 #172, #196, Claus).

Ein Raffstore, der den ganzen Tag unten steht und ueber die Lamellen geregelt
wird, muss je Zustand sagen koennen: "Hoehe unveraendert" oder "Lamellen
unveraendert". Eine leere Zahl heisst "Vorgabe nehmen", nicht "nicht fahren",
deshalb eigene Haken. Dazu die Reihenfolge: viele KNX-Aktoren setzen den Winkel
nach einer Hoehenfahrt zurueck, der Winkel darf erst nach der Hoehe gesendet
werden.

Alle Haken sind aus, wenn der Schluessel fehlt. Die Kontrollfaelle sind der
Bestandsschutz-Teil."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.shutter_pilot.const import (
    AREA_MODE_TIME,
    CONF_AREA_DOWN_ID,
    CONF_AREA_DRIVE_DELAY,
    CONF_AREA_ID,
    CONF_AREA_MODE,
    CONF_AREA_NAME,
    CONF_AREA_TIME_DOWN,
    CONF_AREA_TIME_UP,
    CONF_AREA_UP_ID,
    CONF_AREAS,
    CONF_COVER_ENTITY_ID,
    CONF_DRIVE_AFTER_CLOSE_UP,
    CONF_KEEP_POSITION_CLOSED,
    CONF_KEEP_POSITION_OPEN,
    CONF_KEEP_POSITION_SUN_PROTECT,
    CONF_KEEP_TILT_CLOSED,
    CONF_KEEP_TILT_OPEN,
    CONF_NAME,
    CONF_POSITION_CLOSED,
    CONF_POSITION_OPEN,
    CONF_SHUTTERS,
    CONF_TILT_AFTER_POSITION,
    CONF_TILT_CLOSED,
    CONF_TILT_ENABLED,
    CONF_TILT_OPEN,
    CONF_TILT_SUN_PROTECT,
    CONF_WINDOW_CLOSE_DEBOUNCE,
    CONF_WINDOW_ENTITY_ID,
    CONF_WINDOW_OPEN_STATE,
    CONF_WINDOW_REACT,
    CONF_WINDOW_TILTED_STATE,
    DOMAIN,
)
from custom_components.shutter_pilot.helpers import (
    get_tilt_for_role,
    role_position,
)

BLIND = "cover.raffstore_sued"
DOOR = "binary_sensor.terrassentuer"

AREA = {
    CONF_AREA_ID: "living",
    CONF_AREA_NAME: "Wohnbereich",
    CONF_AREA_MODE: AREA_MODE_TIME,
    CONF_AREA_TIME_UP: "07:00",
    CONF_AREA_TIME_DOWN: "19:00",
    CONF_AREA_DRIVE_DELAY: 0,
}


def _blind(**overrides) -> dict:
    shutter = {
        CONF_COVER_ENTITY_ID: BLIND,
        CONF_NAME: "Sued",
        CONF_AREA_UP_ID: "living",
        CONF_AREA_DOWN_ID: "living",
        CONF_POSITION_OPEN: 21,
        CONF_POSITION_CLOSED: 21,
        CONF_TILT_ENABLED: True,
        CONF_TILT_OPEN: 100,
        CONF_TILT_CLOSED: 60,
        CONF_TILT_SUN_PROTECT: 40,
    }
    shutter.update(overrides)
    return shutter


@pytest.fixture
def calls(hass):
    return {
        "pos": async_mock_service(hass, "cover", "set_cover_position"),
        "tilt": async_mock_service(hass, "cover", "set_cover_tilt_position"),
    }


async def _setup(hass, shutter: dict, position: int = 21):
    hass.states.async_set(
        BLIND, "open", {"current_position": position, "supported_features": 255}
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


async def _tick(hass, data, hour: int, days: int = 1) -> None:
    when = (dt_util.now() + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    data["_minute_callbacks"]["scheduler"](when)
    await hass.async_block_till_done()


def _positions(calls_) -> list[float]:
    return [c.data["position"] for c in calls_["pos"]]


def _tilts(calls_) -> list[float]:
    return [c.data["tilt_position"] for c in calls_["tilt"]]


class TestTheRoleNumbers:
    def test_nothing_set_reads_as_before(self):
        shutter = _blind()
        assert role_position(shutter, "open") == 21
        assert get_tilt_for_role(shutter, "open") == 100

    def test_kept_position_is_none_but_the_number_stays_for_decisions(self):
        from custom_components.shutter_pilot.helpers import get_position_for_role

        shutter = _blind(**{CONF_KEEP_POSITION_OPEN: True})
        assert role_position(shutter, "open") is None
        assert get_position_for_role(shutter, "open") == 21

    def test_kept_tilt_is_none_for_every_role_that_reads_it(self):
        shutter = _blind(**{CONF_KEEP_TILT_CLOSED: True})
        for role in ("closed", "closed_alt", "closed_frost"):
            assert get_tilt_for_role(shutter, role) is None
        assert get_tilt_for_role(shutter, "open") == 100

    def test_a_leftover_flag_without_slats_is_ignored(self):
        shutter = _blind(**{CONF_TILT_ENABLED: False, CONF_KEEP_POSITION_OPEN: True})
        assert role_position(shutter, "open") == 21


class TestScheduleHonoursIt:
    async def test_kept_height_drives_only_the_slats(self, hass, calls):
        _, data = await _setup(hass, _blind(**{CONF_KEEP_POSITION_OPEN: True}))
        await _tick(hass, data, 7)
        assert calls["pos"] == []
        assert _tilts(calls) == [100]

    async def test_without_the_flag_height_and_slats_drive_as_before(
        self, hass, calls
    ):
        _, data = await _setup(hass, _blind())
        await _tick(hass, data, 7)
        assert _positions(calls) == [21]
        assert _tilts(calls) == [100]

    async def test_kept_slats_drive_only_the_height(self, hass, calls):
        _, data = await _setup(
            hass, _blind(**{CONF_KEEP_TILT_CLOSED: True, CONF_POSITION_CLOSED: 0}),
            position=50,
        )
        await _tick(hass, data, 7)  # die Morgenfahrt zuerst, sie ist nicht der Gegenstand
        calls["pos"].clear()
        calls["tilt"].clear()

        await _tick(hass, data, 19)

        assert _positions(calls) == [0]
        assert calls["tilt"] == []

    async def test_both_kept_sends_nothing(self, hass, calls):
        _, data = await _setup(
            hass,
            _blind(**{CONF_KEEP_POSITION_OPEN: True, CONF_KEEP_TILT_OPEN: True}),
        )
        await _tick(hass, data, 7)
        assert calls["pos"] == [] and calls["tilt"] == []

    async def test_a_leftover_flag_without_slats_still_drives(self, hass, calls):
        _, data = await _setup(
            hass, _blind(**{CONF_TILT_ENABLED: False, CONF_KEEP_POSITION_OPEN: True})
        )
        await _tick(hass, data, 7)
        assert _positions(calls) == [21]


class TestGroupServiceAndWaitingDrive:
    async def test_the_shading_button_keeps_the_height(self, hass, calls):
        await _setup(hass, _blind(**{CONF_KEEP_POSITION_SUN_PROTECT: True}))
        await hass.services.async_call(DOMAIN, "sun_protect_group", {}, blocking=True)
        await hass.async_block_till_done()
        assert calls["pos"] == []
        assert _tilts(calls) == [40]

    async def test_a_waiting_drive_with_a_kept_height_runs_the_slats_only(
        self, hass, calls
    ):
        _, data = await _setup(
            hass,
            _blind(
                **{
                    CONF_KEEP_POSITION_OPEN: True,
                    CONF_DRIVE_AFTER_CLOSE_UP: True,
                    CONF_WINDOW_REACT: False,
                    CONF_WINDOW_ENTITY_ID: DOOR,
                    CONF_WINDOW_OPEN_STATE: "on",
                    CONF_WINDOW_TILTED_STATE: "none",
                    CONF_WINDOW_CLOSE_DEBOUNCE: 0,
                }
            ),
        )
        hass.states.async_set(DOOR, "on")
        await hass.async_block_till_done()
        await _tick(hass, data, 7)
        assert calls["tilt"] == []  # wartet auf die Tuer

        hass.states.async_set(DOOR, "off")
        await hass.async_block_till_done()

        assert calls["pos"] == []
        assert _tilts(calls) == [100]


class TestSlatsWaitForTheHeight:
    @pytest.fixture(autouse=True)
    def _fast(self, monkeypatch):
        from custom_components.shutter_pilot import helpers

        monkeypatch.setattr(helpers, "TILT_WAIT_POLL_SEC", 0.01)

    async def test_the_angle_follows_once_the_height_is_there(self, hass, calls):
        _, data = await _setup(
            hass, _blind(**{CONF_TILT_AFTER_POSITION: True}), position=50
        )
        await _tick(hass, data, 7)
        await asyncio.sleep(0.05)
        assert _positions(calls) == [21]
        assert calls["tilt"] == []  # Hoehe noch nicht erreicht

        hass.states.async_set(
            BLIND, "open", {"current_position": 21, "supported_features": 255}
        )
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()

        assert _tilts(calls) == [100]

    async def test_without_the_hook_the_angle_goes_out_with_the_height(
        self, hass, calls
    ):
        """Bestandsschutz."""
        _, data = await _setup(hass, _blind(), position=50)
        await _tick(hass, data, 7)
        assert _positions(calls) == [21]
        assert _tilts(calls) == [100]

    async def test_an_already_reached_height_sends_at_once(self, hass, calls):
        _, data = await _setup(
            hass, _blind(**{CONF_TILT_AFTER_POSITION: True}), position=21
        )
        await _tick(hass, data, 7)
        assert _tilts(calls) == [100]


class TestShadingAndBrightnessHonourIt:
    async def test_shading_with_a_kept_height_drives_the_slats_only(
        self, hass, calls
    ):
        from custom_components.shutter_pilot.const import (
            CONF_AREA_AZIMUTH_ENABLED,
            CONF_AREA_ELEVATION_ENABLED,
            CONF_AREA_ELEVATION_MAX,
            CONF_AREA_ELEVATION_MIN,
            CONF_AREA_SUN_PROTECT_ENABLED,
        )
        from custom_components.shutter_pilot.helpers import is_cover_sun_protected

        hass.states.async_set(
            BLIND, "open", {"current_position": 21, "supported_features": 255}
        )
        hass.states.async_set(
            "sun.sun", "above_horizon", {"elevation": 5.0, "azimuth": 180.0}
        )
        area = {
            CONF_AREA_ID: "living",
            CONF_AREA_NAME: "Wohnbereich",
            CONF_AREA_MODE: AREA_MODE_TIME,
            CONF_AREA_TIME_UP: "07:00",
            CONF_AREA_TIME_DOWN: "19:00",
            CONF_AREA_DRIVE_DELAY: 0,
            CONF_AREA_SUN_PROTECT_ENABLED: True,
            CONF_AREA_ELEVATION_ENABLED: True,
            CONF_AREA_ELEVATION_MIN: 1,
            CONF_AREA_ELEVATION_MAX: 10,
            CONF_AREA_AZIMUTH_ENABLED: False,
        }
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Shutter Pilot",
            options={
                CONF_AREAS: [area],
                CONF_SHUTTERS: [_blind(**{CONF_KEEP_POSITION_SUN_PROTECT: True})],
            },
        )
        entry.add_to_hass(hass)
        with patch(
            "custom_components.shutter_pilot._async_register_panel",
            return_value=None,
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        data = hass.data[DOMAIN][entry.entry_id]

        data["_minute_callbacks"]["elevation"](None)
        await hass.async_block_till_done()

        assert calls["pos"] == []
        assert _tilts(calls) == [40]
        assert is_cover_sun_protected(data, BLIND)

    async def test_brightness_with_a_kept_height_drives_the_slats_only(self, hass):
        from unittest.mock import AsyncMock

        from custom_components.shutter_pilot.brightness import (
            setup_brightness_listener,
        )
        from custom_components.shutter_pilot.const import (
            AREA_MODE_BRIGHTNESS,
            CONF_AREA_BRIGHTNESS_DOWN_THRESHOLD,
            CONF_AREA_BRIGHTNESS_SENSOR,
            CONF_AREA_BRIGHTNESS_UP_THRESHOLD,
            CONF_AREA_W_DOWN_FROM,
            CONF_AREA_W_DOWN_TO,
            CONF_AREA_W_UP_FROM,
            CONF_AREA_W_UP_TO,
            CONF_AREA_WE_DOWN_FROM,
            CONF_AREA_WE_DOWN_TO,
            CONF_AREA_WE_UP_FROM,
            CONF_AREA_WE_UP_TO,
        )

        area = {
            CONF_AREA_ID: "living",
            CONF_AREA_MODE: AREA_MODE_BRIGHTNESS,
            CONF_AREA_BRIGHTNESS_SENSOR: "sensor.lux",
            CONF_AREA_BRIGHTNESS_DOWN_THRESHOLD: 199,
            CONF_AREA_BRIGHTNESS_UP_THRESHOLD: 201,
            CONF_AREA_W_UP_FROM: "00:00", CONF_AREA_W_UP_TO: "23:59",
            CONF_AREA_W_DOWN_FROM: "00:00", CONF_AREA_W_DOWN_TO: "23:59",
            CONF_AREA_WE_UP_FROM: "00:00", CONF_AREA_WE_UP_TO: "23:59",
            CONF_AREA_WE_DOWN_FROM: "00:00", CONF_AREA_WE_DOWN_TO: "23:59",
        }
        hass.states.async_set("sensor.lux", "50")
        entry = MockConfigEntry(
            domain=DOMAIN,
            options={
                CONF_AREAS: [area],
                CONF_SHUTTERS: [_blind(**{CONF_KEEP_POSITION_OPEN: True})],
            },
        )
        entry.add_to_hass(hass)
        hass.data.setdefault(DOMAIN, {}).setdefault(
            entry.entry_id, {"master_enabled": True}
        )
        with patch(
            "custom_components.shutter_pilot.brightness.set_cover_position",
            new=AsyncMock(return_value=True),
        ) as drive:
            await setup_brightness_listener(hass, entry)
            hass.states.async_set("sensor.lux", "5000")
            await hass.async_block_till_done()

        assert drive.await_count == 1
        call = drive.await_args
        assert call.args[3] is None  # Hoehe unveraendert
        assert call.kwargs["tilt_position"] == 100


class TestTheExportSaysSo:
    async def test_the_kept_states_are_named(self, hass, calls):
        from custom_components.shutter_pilot.export import async_build_export

        entry, _ = await _setup(
            hass,
            _blind(
                **{
                    CONF_KEEP_POSITION_OPEN: True,
                    CONF_KEEP_TILT_CLOSED: True,
                    CONF_TILT_AFTER_POSITION: True,
                }
            ),
        )
        md = (await async_build_export(hass, entry))["markdown"]
        assert "Höhe bleibt unverändert bei: auf" in md
        assert "Lamellen bleiben unverändert bei: zu" in md
        assert "erst nach erreichter Höhe" in md

    async def test_a_plain_blind_gets_no_such_block(self, hass, calls):
        from custom_components.shutter_pilot.export import async_build_export

        entry, _ = await _setup(hass, _blind())
        md = (await async_build_export(hass, entry))["markdown"]
        assert "Höhe und Lamellen getrennt" not in md
