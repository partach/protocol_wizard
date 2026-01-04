#------------------------------------------
#-- number.py protocol wizard
#------------------------------------------
"""Protocol-agnostic number platform."""
from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .entity_base import BaseEntityManager, ProtocolWizardNumberBase

_LOGGER = logging.getLogger(__name__)


class NumberManager(BaseEntityManager):
    """Manages number entities for any protocol."""
    
    def _should_create_entity(self, entity_config: dict) -> bool:
        """Create number for write or read-write entities (without options)."""
        # Don't create if it has options (that's a select entity)
        if entity_config.get("options"):
            return False
        return entity_config.get("rw") in ("write", "rw")
    
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
    """Set up number entities for any protocol."""
    coordinator = hass.data[DOMAIN]["coordinators"][entry.entry_id]
    
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title or f"{coordinator.protocol_name.title()} Device",
        manufacturer=coordinator.protocol_name.title(),
        model="Protocol Wizard",
    )
    
    # Set up dynamic number manager
    manager = NumberManager(
        hass=hass,
        entry=entry,
        coordinator=coordinator,
        async_add_entities=async_add_entities,
        device_info=device_info,
    )
    
    # Initial sync
    await manager.sync_entities()
    
    # Re-sync on options change
    remove_listener = entry.add_update_listener(manager.handle_options_update)
    entry.async_on_unload(remove_listener)
