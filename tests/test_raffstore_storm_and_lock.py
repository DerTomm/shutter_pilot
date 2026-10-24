"""Wind protection for venetian blinds and a lock entity (simon42 #193, #196, #202).

Florian: bei Sturm hochfahren (100 %, Lamellen 100 %), eigene Schwelle, Sperrzeit
20 min, und solange der Sturm anhaelt keine automatische Fahrt. Claus: statt
einer Windgeschwindigkeit soll auch der Alarm-Binaersensor der Wetterstation
gehen, und eine Sperr-Entitaet (Aktor-Windalarm, "Fensterputzen") haelt jede
automatische Fahrt eines Covers an.

Der Wind-Slot kann beides schon (Binaersensor, Zahl mit Hysterese, Text); das
Raffstore-Wind-Slot `rwind` ist ein eigener, damit die Markisen unberuehrt
bleiben. Die Kontrollfaelle ohne Haken sind der Bestandsschutz-Teil."""

from __future__ import annotations

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
    CONF_AUTOMATION_LOCK_ENTITY,
    CONF_COVER_ENTITY_ID,
    CONF_NAME,
    CONF_POSITION_CLOSED,
    CONF_POSITION_OPEN,
    CONF_SHUTTERS,
    CONF_STORM_GUARD,
    CONF_TILT_CLOSED,
    CONF_TILT_ENABLED,
    CONF_TILT_OPEN,
    DOMAIN,
    sun_condition_keys,
)

BLIND = "cover.raffstore_sued"
AWNING = "cover.markise"
ALARM = "binary_sensor.windalarm_sued"
WIND = "sensor.windgeschwindigkeit"
LOCK = "input_boolean.fenster_putzen"

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
        CONF_POSITION_OPEN: 0,
        CONF_POSITION_CLOSED: 0,
        CONF_TILT_ENABLED: True,
        CONF_TILT_OPEN: 100,
        CONF_TILT_CLOSED: 60,
    }
    shutter.update(overrides)
    return shutter


def _slot(slot: str, entity: str, **extra) -> dict:
    entity_key, on_key, off_key, _ = sun_condition_keys(slot)
    out = {entity_key: entity}
    out.update(extra)
    return out


@pytest.fixture
def calls(hass):
    return {
        "pos": async_mock_service(hass, "cover", "set_cover_position"),
        "tilt": async_mock_service(hass, "cover", "set_cover_tilt_position"),
    }


async def _setup(hass, shutters: list[dict], options: dict | None = None):
    for cover in (BLIND, AWNING):
        hass.states.async_set(
            cover, "open", {"current_position": 0, "supported_features": 255}
        )
    hass.states.async_set(ALARM, "off")
    hass.states.async_set(WIND, "5")
    hass.states.async_set(LOCK, "off")
    opts = {CONF_AREAS: [AREA], CONF_SHUTTERS: shutters}
    opts.update(options or {})
    entry = MockConfigEntry(domain=DOMAIN, title="Shutter Pilot", options=opts)
    entry.add_to_hass(hass)
    with patch(
        "custom_components.shutter_pilot._async_register_panel", return_value=None
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id]


async def _morning_tick(hass, data, days: int = 1) -> None:
    when = (dt_util.now() + timedelta(days=days)).replace(
        hour=7, minute=0, second=0, microsecond=0
    )
    data["_minute_callbacks"]["scheduler"](when)
    await hass.async_block_till_done()


def _positions(calls_) -> list[float]:
    return [c.data["position"] for c in calls_["pos"]]


# --- Wind: beide Moeglichkeiten --------------------------------------------


class TestStormDrivesTheBlindUp:
    async def test_an_alarm_binary_sensor_triggers_it(self, hass, calls):
        await _setup(
            hass,
            [_blind(**{CONF_STORM_GUARD: True})],
            _slot("rwind", ALARM),
        )
        assert calls["pos"] == []

        hass.states.async_set(ALARM, "on")
        await hass.async_block_till_done()

        assert _positions(calls) == [100]
        assert [c.data["tilt_position"] for c in calls["tilt"]] == [100]

    async def test_a_wind_speed_with_its_own_threshold_triggers_it(
        self, hass, calls
    ):
        await _setup(
            hass,
            [_blind(**{CONF_STORM_GUARD: True})],
            _slot(
                "rwind", WIND, sun_cond_rwind_on_above=60, sun_cond_rwind_off_below=40
            ),
        )
        hass.states.async_set(WIND, "50")  # unter der Blind-Schwelle
        await hass.async_block_till_done()
        assert calls["pos"] == []

        hass.states.async_set(WIND, "70")
        await hass.async_block_till_done()

        assert _positions(calls) == [100]

    async def test_the_target_is_its_own_pair_not_the_open_role(self, hass, calls):
        await _setup(
            hass,
            [_blind(**{CONF_STORM_GUARD: True, "storm_position": 90, "storm_tilt": 80})],
            _slot("rwind", ALARM),
        )
        hass.states.async_set(ALARM, "on")
        await hass.async_block_till_done()

        assert _positions(calls) == [90]
        assert [c.data["tilt_position"] for c in calls["tilt"]] == [80]


class TestExistingSetupsStayUntouched:
    async def test_a_blind_without_the_hook_ignores_the_slot(self, hass, calls):
        await _setup(hass, [_blind()], _slot("rwind", ALARM))
        hass.states.async_set(ALARM, "on")
        await hass.async_block_till_done()
        assert calls["pos"] == []

    async def test_the_awning_wind_sensor_does_not_move_a_blind(self, hass, calls):
        """Die Markisen-Windeinstellung gehoert den Markisen."""
        await _setup(
            hass,
            [_blind(**{CONF_STORM_GUARD: True})],
            _slot("wind", ALARM),
        )
        hass.states.async_set(ALARM, "on")
        await hass.async_block_till_done()
        assert calls["pos"] == []

    async def test_the_blind_slot_does_not_move_an_awning(self, hass, calls):
        awning = {
            CONF_COVER_ENTITY_ID: AWNING,
            CONF_NAME: "Markise",
            "device_kind": "awning",
            CONF_POSITION_OPEN: 0,
        }
        await _setup(hass, [awning], _slot("rwind", ALARM))
        hass.states.async_set(ALARM, "on")
        await hass.async_block_till_done()
        assert calls["pos"] == []


# --- Sperre der automatischen Fahrten --------------------------------------


class TestStormHoldsTheAutomation:
    async def test_the_morning_drive_waits_for_the_storm(self, hass, calls):
        _, data = await _setup(
            hass,
            [_blind(**{CONF_STORM_GUARD: True})],
            _slot("rwind", ALARM, guard_rwind_lockout=0),
        )
        hass.states.async_set(ALARM, "on")
        await hass.async_block_till_done()
        calls["pos"].clear()
        calls["tilt"].clear()

        await _morning_tick(hass, data)

        assert calls["pos"] == [] and calls["tilt"] == []

    async def test_without_a_storm_the_morning_drive_goes_ahead(self, hass, calls):
        _, data = await _setup(
            hass,
            [_blind(**{CONF_STORM_GUARD: True})],
            _slot("rwind", ALARM),
        )

        await _morning_tick(hass, data)

        assert _positions(calls) == [0]

    async def test_hand_drives_stay_free(self, hass, calls):
        _, data = await _setup(
            hass,
            [_blind(**{CONF_STORM_GUARD: True})],
            _slot("rwind", ALARM, guard_rwind_lockout=0),
        )
        hass.states.async_set(ALARM, "on")
        await hass.async_block_till_done()
        calls["pos"].clear()

        await hass.services.async_call(
            DOMAIN, "close_group", {}, blocking=True
        )
        await hass.async_block_till_done()

        assert _positions(calls) == [0]


# --- Sperr-Entitaet ----------------------------------------------------------


class TestLockEntity:
    async def test_a_locked_cover_gets_nothing_automatic(self, hass, calls):
        _, data = await _setup(
            hass, [_blind(**{CONF_AUTOMATION_LOCK_ENTITY: LOCK})]
        )
        hass.states.async_set(LOCK, "on")
        await hass.async_block_till_done()

        await _morning_tick(hass, data)

        assert calls["pos"] == []

    async def test_after_the_lock_the_next_day_runs_again(self, hass, calls):
        _, data = await _setup(
            hass, [_blind(**{CONF_AUTOMATION_LOCK_ENTITY: LOCK})]
        )
        hass.states.async_set(LOCK, "on")
        await hass.async_block_till_done()
        await _morning_tick(hass, data)
        hass.states.async_set(LOCK, "off")
        await hass.async_block_till_done()

        await _morning_tick(hass, data, days=2)

        assert _positions(calls) == [0]

    async def test_without_the_key_nothing_changes(self, hass, calls):
        _, data = await _setup(hass, [_blind()])
        hass.states.async_set(LOCK, "on")  # irgendein Helfer, nicht zugeordnet
        await _morning_tick(hass, data)
        assert _positions(calls) == [0]

    async def test_a_missing_lock_entity_does_not_block(self, hass, calls):
        """Fail open wie der Rollladenschalter."""
        _, data = await _setup(
            hass, [_blind(**{CONF_AUTOMATION_LOCK_ENTITY: "switch.gibt_es_nicht"})]
        )
        await _morning_tick(hass, data)
        assert _positions(calls) == [0]

    async def test_the_storm_goes_ahead_through_a_lock(self, hass, calls):
        await _setup(
            hass,
            [_blind(**{CONF_STORM_GUARD: True, CONF_AUTOMATION_LOCK_ENTITY: LOCK})],
            _slot("rwind", ALARM),
        )
        hass.states.async_set(LOCK, "on")
        hass.states.async_set(ALARM, "on")
        await hass.async_block_till_done()

        assert _positions(calls) == [100]


class TestVerificationRespectsTheLock:
    async def _verify_once(self, hass, entry, monkeypatch, calls) -> None:
        from custom_components.shutter_pilot import cover_verify

        async def _no_sleep(_):
            return

        monkeypatch.setattr(cover_verify.asyncio, "sleep", _no_sleep)
        hass.states.async_set(
            BLIND, "open", {"current_position": 50, "supported_features": 255}
        )
        await cover_verify._verify(hass, entry, BLIND, 0, "Test")
        await hass.async_block_till_done()

    async def test_a_locked_cover_is_not_repeated_or_failed(
        self, hass, calls, monkeypatch
    ):
        entry, _ = await _setup(
            hass, [_blind(**{CONF_AUTOMATION_LOCK_ENTITY: LOCK})]
        )
        hass.states.async_set(LOCK, "on")
        await self._verify_once(hass, entry, monkeypatch, calls)
        assert calls["pos"] == []

    async def test_an_unlocked_cover_is_still_repeated(self, hass, calls, monkeypatch):
        entry, _ = await _setup(hass, [_blind()])
        await self._verify_once(hass, entry, monkeypatch, calls)
        assert calls["pos"] != []


class TestBrightnessAndWindowAreHeldToo:
    async def test_brightness_does_not_drive_a_held_blind(self, hass):
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
                CONF_SHUTTERS: [_blind(**{CONF_STORM_GUARD: True})],
            },
        )
        entry.add_to_hass(hass)
        data = hass.data.setdefault(DOMAIN, {}).setdefault(
            entry.entry_id, {"master_enabled": True}
        )
        data["_awning_guard"] = {BLIND: {"barred": True}}
        with patch(
            "custom_components.shutter_pilot.brightness.set_cover_position",
            new=AsyncMock(return_value=True),
        ) as drive:
            await setup_brightness_listener(hass, entry)
            hass.states.async_set("sensor.lux", "5000")
            await hass.async_block_till_done()
            hass.states.async_set("sensor.lux", "10")
            await hass.async_block_till_done()

        assert drive.await_count == 0


class TestTheExportShowsBoth:
    async def test_storm_table_and_lock_row_appear(self, hass, calls):
        from custom_components.shutter_pilot.export import async_build_export

        entry, _ = await _setup(
            hass,
            [
                _blind(
                    **{CONF_STORM_GUARD: True, CONF_AUTOMATION_LOCK_ENTITY: LOCK}
                )
            ],
            _slot("rwind", ALARM),
        )
        hass.states.async_set(LOCK, "on")
        await hass.async_block_till_done()

        md = (await async_build_export(hass, entry))["markdown"]

        assert "Windschutz (Raffstore)" in md
        assert f"`{ALARM}`" in md
        assert "Sperr-Entität" in md and "gesperrt" in md

    async def test_a_plain_blind_gets_neither(self, hass, calls):
        from custom_components.shutter_pilot.export import async_build_export

        entry, _ = await _setup(hass, [_blind()])

        md = (await async_build_export(hass, entry))["markdown"]

        assert "Windschutz (Raffstore)" not in md
        assert "Sperr-Entität" not in md
