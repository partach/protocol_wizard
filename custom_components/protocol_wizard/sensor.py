#------------------------------------------
#-- sensor.py protocol wizard
#------------------------------------------
"""Protocol-agnostic sensor platform."""
from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, CONF_PROTOCOL, CONF_PROTOCOL_MODBUS
from .entity_base import (
    BaseEntityManager,
    ProtocolWizardSensorBase,
    ProtocolWizardHubEntity,
    ModbusSlaveIdEntity,
    ModbusConnectionInfoEntity,
    get_all_coordinators_for_entry,
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
    """Set up sensor entities for all coordinators in this entry."""
    coordinators = get_all_coordinators_for_entry(hass, entry)

    # Store managers to prevent garbage collection (weak refs in update_listener)
    if "entity_managers" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["entity_managers"] = {}

    # Clean up any existing managers from previous setup (prevents duplicates on reload)
    old_managers = hass.data[DOMAIN]["entity_managers"].get(entry.entry_id, [])
    for manager in old_managers:
        if hasattr(manager, '_unsub_dispatcher') and manager._unsub_dispatcher:
            manager._unsub_dispatcher()
    hass.data[DOMAIN]["entity_managers"][entry.entry_id] = []

    # Check if this is a Modbus device
    is_modbus = entry.data.get(CONF_PROTOCOL) == CONF_PROTOCOL_MODBUS

    # Track if connection info entity was already added (shared across slaves)
    connection_info_added = False

    for coordinator, device_info in coordinators:
        # Add hub status entity per coordinator
        hub_entity = ProtocolWizardHubEntity(
            coordinator=coordinator,
            entry=entry,
            device_info=device_info,
        )

        diagnostic_entities = [hub_entity]

        # Add Modbus-specific diagnostic entities
        if is_modbus:
            # Slave ID entity (per slave)
            slave_id_entity = ModbusSlaveIdEntity(
                coordinator=coordinator,
                entry=entry,
                device_info=device_info,
            )
            diagnostic_entities.append(slave_id_entity)

            # Connection info entity (only add once for the first slave)
            if not connection_info_added:
                connection_info_entity = ModbusConnectionInfoEntity(
                    coordinator=coordinator,
                    entry=entry,
                    device_info=device_info,
                )
                diagnostic_entities.append(connection_info_entity)
                connection_info_added = True

        async_add_entities(diagnostic_entities)

        # Set up dynamic sensor manager
        manager = SensorManager(
            hass=hass,
            entry=entry,
            coordinator=coordinator,
            async_add_entities=async_add_entities,
            device_info=device_info,
        )

        # Store reference to prevent GC
        hass.data[DOMAIN]["entity_managers"][entry.entry_id].append(manager)

        # Initial sync
        await manager.sync_entities()

        # Subscribe to dispatcher signal for entity sync
        manager.subscribe_to_entity_sync()

        # Also register traditional update listener (may work if manager stays alive)
        _LOGGER.debug("[Sensor] Registering update listener for coordinator %s",
                     getattr(coordinator, 'coordinator_key', 'unknown'))
        remove_listener = entry.add_update_listener(manager.handle_options_update)
        entry.async_on_unload(remove_listener)
