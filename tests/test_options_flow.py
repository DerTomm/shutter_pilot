"""Options flow must not depend on Home Assistant setting ``config_entry``.

HA assigns ``OptionsFlow.config_entry`` itself only from 2024.11 on; hacs.json
declares 2024.6. Review note from the HACS default-store PR (hacs/default#9592).
"""

from __future__ import annotations

from homeassistant.data_entry_flow import FlowResultType

from custom_components.shutter_pilot.config_flow import ShutterPilotOptionsFlow
from custom_components.shutter_pilot.const import CONF_AREAS, CONF_SHUTTERS


async def test_options_flow_through_home_assistant(hass, entry):
    """The Configure dialog opens and saves without touching the options."""
    before = dict(entry.options)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["description_placeholders"]["area_count"] == str(
        len(before.get(CONF_AREAS, []))
    )
    assert result["description_placeholders"]["shutter_count"] == str(
        len(before.get(CONF_SHUTTERS, []))
    )

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == before


async def test_options_flow_without_handler_assigned_entry(hass, entry):
    """Simulates HA < 2024.11: nobody sets ``config_entry`` on the flow.

    On current HA, reading ``self.config_entry`` here raises because no
    handler is bound – exactly the old code path that broke on 2024.6–2024.10.
    """
    flow = ShutterPilotOptionsFlow(entry)
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["type"] == FlowResultType.FORM
    assert result["description_placeholders"]["shutter_count"] == str(
        len(entry.options.get(CONF_SHUTTERS, []))
    )
