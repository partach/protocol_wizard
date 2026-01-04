#------------------------------------------
#-- select.py protocol wizard
#------------------------------------------
"""Protocol-agnostic select platform."""
from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .entity_base import BaseEntityManager, ProtocolWizardSelectBase

_LOGGER = logging.getLogger(__name__)


class SelectManager(BaseEntityManager):
    """Manages select entities for any protocol."""
    
    def _should_create_entity(self, entity_config: dict) -> bool:
        """Create select for entities with options mapping."""
        return bool(entity_config.get("options"))
    
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
    """Set up select entities for any protocol."""
    coordinator = hass.data[DOMAIN]["coordinators"][entry.entry_id]
    
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title or f"{coordinator.protocol_name.title()} Device",
        manufacturer=coordinator.protocol_name.title(),
        model="Protocol Wizard",
    )
    
    # Set up dynamic select manager
    manager = SelectManager(
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
