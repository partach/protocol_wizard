#------------------------------------------
#-- base entity_base.py protocol wizard
#------------------------------------------

"""Protocol-agnostic base entity classes."""
from __future__ import annotations

import logging
from typing import Any
from abc import ABC, abstractmethod

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo, Entity, EntityCategory
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.number import NumberEntity,NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.components.switch import SwitchEntity
from .const import (
    CONF_ENTITIES,
    CONF_REGISTERS,
    CONF_PROTOCOL_MODBUS,
    CONF_PROTOCOL,
)
from .protocols.base import BaseProtocolCoordinator

_LOGGER = logging.getLogger(__name__)


class BaseEntityManager(ABC):
    """
    Base class for managing dynamic entity lifecycle.
    Handles the common pattern of sync/add/remove entities.
    """
    
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: BaseProtocolCoordinator,
        async_add_entities,
        device_info: DeviceInfo,
    ):
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.async_add_entities = async_add_entities
        self.device_info = device_info
        self.entities: dict[str, Entity] = {}
        self.ent_reg = er.async_get(hass)
    
    @abstractmethod
    def _should_create_entity(self, entity_config: dict) -> bool:
        """Determine if entity should be created for this config."""
        pass
    
    @abstractmethod
    def _create_entity(self, entity_config: dict, unique_id: str, key: str) -> Entity:
        """Create the appropriate entity type."""
        pass
    
    @abstractmethod
    def _get_entity_type_suffix(self) -> str:
        """Get suffix for unique_id (e.g., 'sensor', 'number')."""
        pass
    
    def _get_entities_config_key(self) -> str:
        """Get the config key for entities list. Override if protocol uses different key."""
        # Most protocols will use CONF_ENTITIES but Modbus uses CONF_REGISTERS
        protocol = self.entry.data.get(CONF_PROTOCOL, CONF_PROTOCOL_MODBUS)
        if protocol == CONF_PROTOCOL_MODBUS:
            return CONF_REGISTERS
        return CONF_ENTITIES
    
    def _entity_key(self, name: str) -> str:
        """Generate consistent key from entity name."""
        return name.lower().strip().replace(" ", "_")
    
    def _unique_id(self, entity_config: dict) -> str:
        """Generate stable unique_id."""
        address = entity_config.get("address", "unknown")
        entity_type = entity_config.get("register_type") or entity_config.get("entity_type", "auto")
        suffix = self._get_entity_type_suffix()
        return f"{self.entry.entry_id}_{address}_{entity_type}_{suffix}"
    
    async def sync_entities(self) -> None:
        """Create, update, and remove entities based on current config."""
        config_key = self._get_entities_config_key()
        current_configs = self.entry.options.get(config_key, [])
        desired_ids = set()
        new_entities: list[Entity] = []
        
        for config in current_configs:
            if not self._should_create_entity(config):
                continue
            
            unique_id = self._unique_id(config)
            desired_ids.add(unique_id)
            
            if unique_id in self.entities:
                continue  # Entity already exists
            
            entity = self._create_entity(
                entity_config=config,
                unique_id=unique_id,
                key=self._entity_key(config["name"]),
            )
            
            self.entities[unique_id] = entity
            new_entities.append(entity)
        
        if new_entities:
            self.async_add_entities(new_entities)
            _LOGGER.debug(
                "Added %d %s entities",
                len(new_entities),
                self._get_entity_type_suffix()
            )
        
        # Remove entities that are no longer in config
        for uid in list(self.entities):
            if uid not in desired_ids:
                entity = self.entities.pop(uid)
                if entity.entity_id:
                    self.ent_reg.async_remove(entity.entity_id)
                    _LOGGER.debug("Removed entity %s", entity.entity_id)
                await entity.async_remove()
        
        _LOGGER.info(
            "%s sync complete — active=%d, defined=%d",
            self._get_entity_type_suffix().title(),
            len(self.entities),
            len([c for c in current_configs if self._should_create_entity(c)]),
        )
    
    async def handle_options_update(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Handle options update callback."""
        await self.sync_entities()


class ProtocolWizardSensorBase(CoordinatorEntity, SensorEntity):
    """Protocol-agnostic sensor entity."""
    
    _attr_has_entity_name = True
    _attr_should_poll = False
    
    def __init__(
        self,
        coordinator: BaseProtocolCoordinator,
        entry: ConfigEntry,
        unique_id: str,
        key: str,
        entity_config: dict[str, Any],
        device_info: DeviceInfo,
    ):
        super().__init__(coordinator)
        self._key = key
        self._config = entity_config
        
        self._attr_unique_id = unique_id
        self._attr_name = entity_config.get("name")
        self._attr_device_class = entity_config.get("device_class")
        self._attr_device_info = device_info
        
        # Set display precision based on data type
        data_type = entity_config.get("data_type", "")
        if not entity_config.get("format"):
            self._attr_native_unit_of_measurement = entity_config.get("unit")
            data_type = entity_config.get("data_type", "")
            if "float" in data_type.lower():
                self._attr_suggested_display_precision = entity_config.get("precision", 2)
            elif any(t in data_type.lower() for t in ["int", "uint"]):
                self._attr_suggested_display_precision = 0
    
    @property
    def native_value(self):
        return self.coordinator.data.get(self._key)
    
    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def extra_state_attributes(self):
        """Return extra state attributes for walk output."""
        attrs = super().extra_state_attributes or {}

        # Check if coordinator has raw data for this entity
        raw_key = f"{self._key}_raw"
        if raw_key in self.coordinator.data:
            attrs["raw_output"] = self.coordinator.data[raw_key]

        return attrs


class ProtocolWizardNumberBase(CoordinatorEntity, NumberEntity):
    """Protocol-agnostic number entity."""
    
    _attr_has_entity_name = True
    _attr_should_poll = False
    
    def __init__(
        self,
        coordinator: BaseProtocolCoordinator,
        entry: ConfigEntry,
        unique_id: str,
        key: str,
        entity_config: dict[str, Any],
        device_info: DeviceInfo,
    ):
        super().__init__(coordinator)
        self._key = key
        self._config = entity_config
        
        self._attr_unique_id = unique_id
        self._attr_name = entity_config.get("name")
        self._attr_device_info = device_info
        
        self._attr_native_min_value = entity_config.get("min")
        self._attr_native_max_value = entity_config.get("max")
        self._attr_native_step = entity_config.get("step", 1)
        
        # Set display precision
        self.data_type = entity_config.get("data_type", "")
        if not entity_config.get("format"):
            self._attr_native_unit_of_measurement = entity_config.get("unit")
            if "float" in self.data_type.lower():
                self._attr_suggested_display_precision = entity_config.get("precision", 2)
            elif any(t in self.data_type.lower() for t in ["int", "uint"]):
                self._attr_suggested_display_precision = 0
    
    @property
    def native_value(self):
        return self.coordinator.data.get(self._key)
        
    @property
    def native_min_value(self) -> float | None:
        return self._config.get("min")

    @property
    def native_max_value(self) -> float | None:
        return self._config.get("max")

    @property
    def native_step(self) -> float | None:
        return self._config.get("step", 1.0)

    @property
    def mode(self) -> NumberMode:
        """Return the mode of the number entity."""
        return NumberMode.BOX  # ← This forces the box input instead of slider
    
    async def async_set_native_value(self, value: float) -> None:
        """Write value to protocol."""
        if self._config.get("rw") not in ("write", "rw"):
            _LOGGER.warning(
                "Blocked write to read-only entity %s",
                self._config.get("name"),
            )
            return
        
        # Check register type
        register_type = self._config.get("register_type", "holding").lower()
        
        # For coils/discrete (bit types), convert to boolean
        if register_type in ("coil", "discrete"):
            value = bool(int(float(value)))  # "0" → False, "1" → True
        elif "float" not in self.data_type:
            value = int(round(float(value)))  # Regular registers
        else:
            value = float(value)  # Float registers
        
        # Use coordinator's write method
        success = await self.coordinator.async_write_entity(
            address=str(self._config["address"]),
            value=value,
            entity_config=self._config,
        )
        
        if success:
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to write value to %s", self._config.get("name"))

class ProtocolWizardSwitchBase(CoordinatorEntity, SwitchEntity):
    """Protocol-agnostic switch entity (for coils)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        unique_id: str,
        key: str,
        entity_config: dict,
        device_info: DeviceInfo,
    ):
        super().__init__(coordinator)
        self._key = key
        self._config = entity_config
        self._attr_unique_id = unique_id
        self._attr_name = entity_config.get("name")
        self._attr_device_info = device_info
        self._attr_icon = "mdi:toggle-switch"

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        value = self.coordinator.data.get(self._key)
        return bool(value)

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        await self.coordinator.async_write_entity(
            address=str(self._config["address"]),
            value=True,
            entity_config=self._config,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        await self.coordinator.async_write_entity(
            address=str(self._config["address"]),
            value=False,
            entity_config=self._config,
        )
        await self.coordinator.async_request_refresh()

class ProtocolWizardSelectBase(CoordinatorEntity, SelectEntity):
    """Protocol-agnostic select entity."""
    
    _attr_has_entity_name = True
    _attr_should_poll = False
    
    def __init__(
        self,
        coordinator: BaseProtocolCoordinator,
        entry: ConfigEntry,
        unique_id: str,
        key: str,
        entity_config: dict[str, Any],
        device_info: DeviceInfo,
    ):
        super().__init__(coordinator)
        self._key = key
        self._config = entity_config
        
        self._attr_unique_id = unique_id
        self._attr_name = entity_config.get("name")
        self._attr_device_info = device_info
        self.data_type = entity_config.get("data_type", "")
        
        # Build value mapping from options dict
        options_dict = entity_config.get("options", {})
        self._value_map = {str(k): v for k, v in options_dict.items()}
        self._reverse_map = {v: k for k, v in self._value_map.items()}
        
        self._attr_options = list(self._reverse_map.keys())
    
    @property
    def current_option(self):
        raw = self.coordinator.data.get(self._key)
        return self._value_map.get(str(raw))
    
    async def async_select_option(self, option: str) -> None:
        """Write selected option to protocol."""
        value = self._reverse_map.get(option)
        if value is None:
            return
        
        if self._config.get("rw") not in ("write", "rw"):
            _LOGGER.warning(
                "Blocked write to read-only entity %s",
                self._config.get("name"),
            )
            return
        
        # Convert to appropriate type
        register_type = self._config.get("register_type", "holding").lower()
        
        # For coils/discrete (bit types), convert to boolean
        if register_type in ("coil", "discrete"):
            value = bool(int(float(value)))  # "0" → False, "1" → True
        elif "float" not in self.data_type:
            value = int(round(float(value)))  # Regular registers
        else:
            value = float(value)  # Float registers
        
        # Use coordinator's write method
        success = await self.coordinator.async_write_entity(
            address=str(self._config["address"]),
            value=value,
            entity_config=self._config,
        )
        
        if success:
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to write value to %s", self._config.get("name"))


class ProtocolWizardHubEntity(CoordinatorEntity, SensorEntity):
    """Hub status entity - shows connection state."""
    
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lan-connect"
    
    def __init__(
        self,
        coordinator: BaseProtocolCoordinator,
        entry: ConfigEntry,
        device_info: DeviceInfo,
    ):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_hub"
        self._attr_name = f"{coordinator.protocol_name.title()} Hub"
        self._attr_device_info = device_info
        self._attr_extra_state_attributes = {
            "protocol": self.coordinator.protocol_name,
            "device_id": self.coordinator.config_entry.data.get("device_id"),
        }
    
    @property
    def native_value(self):
        try:
            return "connected" if self.coordinator.client.is_connected else "disconnected"
        except Exception as err:
            _LOGGER.error("Failed to get hub status: %s", err)
            return "unknown"
