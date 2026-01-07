# custom_components/protocol_wizard/switch.py
"""Protocol-agnostic switch platform (for coils)."""
from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo


from .const import DOMAIN
from .entity_base import BaseEntityManager, ProtocolWizardSwitchBase

_LOGGER = logging.getLogger(__name__)


class SwitchManager(BaseEntityManager):
    """Manages switch entities (coils)."""

    def _should_create_entity(self, entity_config: dict) -> bool:
        """Create switch for writeable coils only."""
        reg_type = entity_config.get("register_type", "holding").lower()
        rw = entity_config.get("rw", "read")
        return reg_type == "coil" and rw in ("write", "rw")

    def _create_entity(self, entity_config: dict, unique_id: str, key: str):
        return ProtocolWizardSwitchBase(
            coordinator=self.coordinator,
            entry=self.entry,
            unique_id=unique_id,
            key=key,
            entity_config=entity_config,
            device_info=self.device_info,
        )

    def _get_entity_type_suffix(self) -> str:
        return "switch"

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
):
    """Set up switch entities."""
    coordinator = hass.data[DOMAIN]["coordinators"][entry.entry_id]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title or f"{coordinator.protocol_name.title()} Device",
        manufacturer=coordinator.protocol_name.title(),
        model="Protocol Wizard",
    )

    manager = SwitchManager(
        hass=hass,
        entry=entry,
        coordinator=coordinator,
        async_add_entities=async_add_entities,
        device_info=device_info,
    )

    await manager.sync_entities()

    remove_listener = entry.add_update_listener(manager.handle_options_update)
    entry.async_on_unload(remove_listener)
