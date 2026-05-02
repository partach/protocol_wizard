#------------------------------------------
#-- number.py protocol wizard
#------------------------------------------
"""Protocol-agnostic number platform."""
from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN
from .entity_base import BaseEntityManager, ProtocolWizardNumberBase, get_all_coordinators_for_entry

_LOGGER = logging.getLogger(__name__)


class NumberManager(BaseEntityManager):
    """Manages number entities for any protocol."""

    def _should_create_entity(self, entity_config: dict) -> bool:
        """Create number only for writeable registers that are NOT coils."""
        rw = entity_config.get("rw", "read")
        reg_type = entity_config.get("register_type", "holding").lower()

        # Do not create number for coils (they are binary -> use switch/select)
        if reg_type == "coil":
            return False

        # Do not create if it has options (that's a select)
        if entity_config.get("options"):
            return False

        return rw in ("write", "rw")

    def _create_entity(self, entity_config: dict, unique_id: str, key: str):
        """Create a number entity."""
        return ProtocolWizardNumberBase(
            coordinator=self.coordinator,
            entry=self.entry,
            unique_id=unique_id,
            key=key,
            entity_config=entity_config,
            device_info=self.device_info,
        )

    def _get_entity_type_suffix(self) -> str:
        return "number"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
):
    """Set up number entities for all coordinators in this entry."""
    coordinators = get_all_coordinators_for_entry(hass, entry)

    # Store managers to prevent garbage collection (weak refs in update_listener)
    if "entity_managers" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["entity_managers"] = {}

    # Note: Manager list cleanup is handled by sensor.py which runs first,
    # or during unload. Just ensure the list exists.
    if entry.entry_id not in hass.data[DOMAIN]["entity_managers"]:
        hass.data[DOMAIN]["entity_managers"][entry.entry_id] = []

    for coordinator, device_info in coordinators:
        manager = NumberManager(
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
