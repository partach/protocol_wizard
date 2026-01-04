#------------------------------------------
#-- sensor.py protocol wizard
#------------------------------------------
"""Protocol-agnostic sensor platform."""
from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .entity_base import (
    BaseEntityManager,
    ProtocolWizardSensorBase,
    ProtocolWizardHubEntity,
)

_LOGGER = logging.getLogger(__name__)


class SensorManager(BaseEntityManager):
    """Manages sensor entities for any protocol."""
    
    def _should_create_entity(self, entity_config: dict) -> bool:
        """Create sensor for read or read-write entities."""
        return entity_config.get("rw", "read") in ("read", "rw")
    
    def _create_entity(self, entity_config: dict, unique_id: str, key: str):
        """Create a sensor entity."""
        return ProtocolWizardSensorBase(
            coordinator=self.coordinator,
            entry=self.entry,
            unique_id=unique_id,
            key=key,
            entity_config=entity_config,
            device_info=self.device_info,
        )
    
    def _get_entity_type_suffix(self) -> str:
        return "sensor"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
):
    """Set up sensor entities for any protocol."""
    coordinator = hass.data[DOMAIN]["coordinators"][entry.entry_id]
    
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title or f"{coordinator.protocol_name.title()} Device",
        manufacturer=coordinator.protocol_name.title(),
        model="Protocol Wizard",
    )
    
    # Add hub status entity
    hub_entity = ProtocolWizardHubEntity(
        coordinator=coordinator,
        entry=entry,
        device_info=device_info,
    )
    async_add_entities([hub_entity])
    
    # Set up dynamic sensor manager
    manager = SensorManager(
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
