#------------------------------------------
#-- select.py protocol wizard
#------------------------------------------
"""Protocol-agnostic select platform."""
from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
# from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .entity_base import BaseEntityManager, ProtocolWizardSelectBase, get_all_coordinators_for_entry

_LOGGER = logging.getLogger(__name__)


class SelectManager(BaseEntityManager):
    """Manages select entities for any protocol."""

    def _should_create_entity(self, entity_config: dict) -> bool:
        """Create select for writable entities with options mapping."""
        has_options = bool(entity_config.get("options"))
        is_writable = entity_config.get("rw") in ("rw", "write")
        return has_options and is_writable

    def _create_entity(self, entity_config: dict, unique_id: str, key: str):
        """Create a select entity."""
        return ProtocolWizardSelectBase(
            coordinator=self.coordinator,
            entry=self.entry,
            unique_id=unique_id,
            key=key,
            entity_config=entity_config,
            device_info=self.device_info,
        )

    def _get_entity_type_suffix(self) -> str:
        return "select"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
):
    """Set up select entities for all coordinators in this entry."""
    coordinators = get_all_coordinators_for_entry(hass, entry)

    # Store managers to prevent garbage collection (weak refs in update_listener)
    if "entity_managers" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["entity_managers"] = {}

    # Note: Manager list cleanup is handled by sensor.py which runs first,
    # or during unload. Just ensure the list exists.
    if entry.entry_id not in hass.data[DOMAIN]["entity_managers"]:
        hass.data[DOMAIN]["entity_managers"][entry.entry_id] = []

    for coordinator, device_info in coordinators:
        manager = SelectManager(
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
