# custom_components/protocol_wizard/switch.py
"""Protocol-agnostic switch platform (for coils)."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .entity_base import (
    BaseEntityManager,
    ProtocolWizardSwitchBase,
    get_all_coordinators_for_entry,
)

_LOGGER = logging.getLogger(__name__)


class SwitchManager(BaseEntityManager):
    """Manages switch entities (coils and switch_options)."""

    def _should_create_entity(self, entity_config: dict) -> bool:
        """Create switch for writeable coils or entities with switch_options."""
        rw = entity_config.get("rw", "read")
        is_writable = rw in ("write", "rw")

        # If switch_options exists -> create switch with value mapping
        if entity_config.get("switch_options") and is_writable:
            return True

        # If regular options exist -> let select handle it
        if entity_config.get("options"):
            return False

        # For coils without options
        reg_type = entity_config.get("register_type", "holding").lower()
        return reg_type == "coil" and is_writable

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
    """Set up switch entities for all coordinators in this entry."""
    coordinators = get_all_coordinators_for_entry(hass, entry)

    # Store managers to prevent garbage collection (weak refs in update_listener)
    if "entity_managers" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["entity_managers"] = {}

    # Note: Manager list cleanup is handled by sensor.py which runs first,
    # or during unload. Just ensure the list exists.
    if entry.entry_id not in hass.data[DOMAIN]["entity_managers"]:
        hass.data[DOMAIN]["entity_managers"][entry.entry_id] = []

    for coordinator, device_info in coordinators:
        manager = SwitchManager(
            hass=hass,
            entry=entry,
            coordinator=coordinator,
            async_add_entities=async_add_entities,
            device_info=device_info,
        )

        # Store reference to prevent GC
        hass.data[DOMAIN]["entity_managers"][entry.entry_id].append(manager)

        await manager.sync_entities()

        # Subscribe to dispatcher signal for entity sync
        manager.subscribe_to_entity_sync()

        remove_listener = entry.add_update_listener(manager.handle_options_update)
        entry.async_on_unload(remove_listener)
