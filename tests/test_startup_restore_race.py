"""Neustart am Abend: die erste Meldung nach dem Start darf die gespeicherte
Position nicht ueberschreiben, bevor die Wiederherstellung sie gelesen hat.

mag2000 (community.simon42.com/90112/201): Rollos abends durch Shutter Pilot
zugefahren, Home Assistant neu gestartet, danach fahren alle hoch. Der
Positionsspeicher liefert der Wiederherstellung dasselbe Dict, das der Tracker
beschreibt (`async_load()` gibt `self._covers` zurueck). Meldet ein Cover nach
dem Start zuerst eine Standardposition (100 %), schreibt der Tracker sie als
"manual" in genau dieses Dict - die Wiederherstellung nach 5 s vergleicht dann
100 mit 100 und fasst nichts an."""

from __future__ import annotations

import pytest

from custom_components.shutter_pilot import cover_tracker
from custom_components.shutter_pilot.position_store import (
    SOURCE_AUTOMATION,
    get_position_store,
)

COVER = "cover.living_room"


async def _restart_store(store) -> None:
    """Der Speicher liest nach einem Neustart frisch von der Platte."""
    store._covers = None
    await store.async_load()


@pytest.fixture(autouse=True)
def _fast_startup(monkeypatch):
    monkeypatch.setattr(cover_tracker, "STARTUP_RESTORE_DELAY_SEC", 0)
    monkeypatch.setattr(cover_tracker, "STARTUP_RESTORE_RETRY_SEC", 0)


async def test_first_report_after_restart_does_not_erase_the_stored_position(
    hass, entry
):
    calls: list = []

    async def _handler(call):
        calls.append(call)
        hass.states.async_set(
            call.data["entity_id"],
            "open",
            {"current_position": call.data["position"], "supported_features": 15},
        )

    hass.services.async_register("cover", "set_cover_position", _handler)

    # Der Abend: Shutter Pilot hat zugefahren, der Speicher weiss es.
    store = get_position_store(hass, entry.entry_id)
    await store.async_set_position(COVER, 10, SOURCE_AUTOMATION)
    await _restart_store(store)

    # Neustart: das Cover verschwindet und meldet sich mit der Standardposition.
    hass.states.async_set(COVER, "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set(
        COVER, "open", {"current_position": 100, "supported_features": 15}
    )
    await hass.async_block_till_done()

    await cover_tracker.async_restore_positions_on_startup(hass, entry)
    await hass.async_block_till_done()

    assert [c.data["position"] for c in calls] == [10]


async def test_the_restored_cover_counts_as_down_not_up(hass, entry):
    """Die Startmeldung 100 % bucht der Tracker als "oben". Nach der
    Wiederherstellung auf 10 % muss der Rollladen wieder als "unten" gelten,
    sonst ueberspringt ihn der naechste Morgen."""

    async def _handler(call):
        hass.states.async_set(
            call.data["entity_id"],
            "open",
            {"current_position": call.data["position"], "supported_features": 15},
        )

    hass.services.async_register("cover", "set_cover_position", _handler)
    store = get_position_store(hass, entry.entry_id)
    await store.async_set_position(COVER, 10, SOURCE_AUTOMATION)
    await _restart_store(store)
    hass.states.async_set(COVER, "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set(
        COVER, "open", {"current_position": 100, "supported_features": 15}
    )
    await hass.async_block_till_done()

    await cover_tracker.async_restore_positions_on_startup(hass, entry)
    await hass.async_block_till_done()

    data = hass.data["shutter_pilot"][entry.entry_id]
    assert COVER in data["covers_driven_down"]
    assert COVER not in data["covers_driven_up"]


async def test_a_matching_report_is_left_alone(hass, entry):
    """Bestandsschutz: meldet das Cover nach dem Start die gespeicherte
    Position, wird nichts gefahren."""
    calls: list = []

    async def _handler(call):
        calls.append(call)

    hass.services.async_register("cover", "set_cover_position", _handler)
    store = get_position_store(hass, entry.entry_id)
    await store.async_set_position(COVER, 10, SOURCE_AUTOMATION)
    await _restart_store(store)
    hass.states.async_set(COVER, "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set(
        COVER, "closed", {"current_position": 10, "supported_features": 15}
    )
    await hass.async_block_till_done()

    await cover_tracker.async_restore_positions_on_startup(hass, entry)
    await hass.async_block_till_done()

    assert calls == []
