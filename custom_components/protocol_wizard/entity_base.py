#------------------------------------------
#-- base entity_base.py protocol wizard
#------------------------------------------

"""Protocol-agnostic base entity classes."""
from __future__ import annotations

import logging
from typing import Any
from abc import ABC, abstractmethod
import json
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo, Entity, EntityCategory
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.number import NumberEntity,NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.components.switch import SwitchEntity
from .const import (
    CONF_ENTITIES,
    CONF_REGISTERS,
    CONF_PROTOCOL_MODBUS,
#    CONF_PROTOCOL_SNMP,
    CONF_PROTOCOL_MQTT,
    CONF_PROTOCOL_BACNET,
    CONF_PROTOCOL,
    CONF_SLAVES,
    CONF_BACNET_DEVICES,
    SIGNAL_ENTITY_SYNC,
)
from .protocols.base import BaseProtocolCoordinator

_LOGGER = logging.getLogger(__name__)

def apply_common_entity_attributes(
    entity: Entity,
    entity_config: dict[str, Any],
    hass: HomeAssistant | None = None,
) -> None:
    """
    Apply common attributes (device_class, state_class, entity_category, icon, unit, precision)
    from entity_config to any HA entity (Sensor, Number, Select, Switch, etc.).
    """
    # Device class
    entity._attr_device_class = entity_config.get("device_class")

    # State class (only for Sensor/Number)
    if isinstance(entity, (SensorEntity, NumberEntity)):
        entity._attr_state_class = entity_config.get("state_class")

    # Entity category (map string to enum)
    category_str = entity_config.get("entity_category")
    if category_str:
        try:
            entity._attr_entity_category = EntityCategory(category_str)
        except ValueError:
            _LOGGER.warning("Invalid entity_category '%s' - using None", category_str)
            entity._attr_entity_category = None

    # Icon
    if entity_config.get("icon"): 
        entity._attr_icon = entity_config.get("icon")
        

    # Display precision (only for sensor/number if no custom format)
    if isinstance(entity, (SensorEntity, NumberEntity)) and not entity_config.get("format"):
        data_type = entity_config.get("data_type", "")
        entity._attr_native_unit_of_measurement = entity_config.get("unit") # only set unit if we don't try to format it
        if "float" in data_type.lower():
            entity._attr_suggested_display_precision = entity_config.get("precision", 2)
        elif any(t in data_type.lower() for t in ["int", "uint"]):
            entity._attr_suggested_display_precision = 0

def get_safe_number_defaults(data_type: str) -> dict[str, float]:
    """
    Returns safe default min/max/step values based on data_type.
    Used for NumberEntity to prevent NoneType errors on write.
    """
    data_type = data_type.lower()

    # Integer types (signed/unsigned 16/32 bit)
    if "uint16" in data_type:
        return {"min": 0.0, "max": 65535.0, "step": 1.0}
    if "int16" in data_type:
        return {"min": -32768.0, "max": 32767.0, "step": 1.0}
    if "uint32" in data_type:
        return {"min": 0.0, "max": 4294967295.0, "step": 1.0}
    if "int32" in data_type:
        return {"min": -2147483648.0, "max": 2147483647.0, "step": 1.0}
    if "uint64" in data_type:
        return {"min": 0.0, "max": 1.8446744e+19, "step": 1.0}  # approx max uint64
    if "int64" in data_type:
        return {"min": -9.223372e+18, "max": 9.223372e+18, "step": 1.0}  # approx max int64

    # Float types
    if "float" in data_type:
        # Reasonable wide range for most sensors (can be overridden)
        return {"min": -1000000.0, "max": 1000000.0, "step": 0.1}

    # Fallback for unknown types
    return {"min": 0.0, "max": 100.0, "step": 1.0}

def set_readonly_protocol_settings(entity: Entity, entity_config: dict[str, Any]) -> None:
    """
    Attach all relevant protocol settings as a read-only dict in extra_state_attributes.
    Called once per entity in __init__.
    The dict is frozen/immutable to prevent accidental changes.
    """
    # Build the settings dict (only include meaningful fields)
    settings = {
        k: entity_config[k]
        for k in [
            "address", "register_type", "data_type", "rw", "scale", "offset",
            "format", "options", "byte_order", "word_order", "size", "min", "max", "step",
            "device_class", "state_class", "entity_category", "icon", "unit"
        ]
        if k in entity_config
    }

    # Optional: Clean up None values (makes attributes cleaner)
    settings = {k: v for k, v in settings.items() if v is not None}

    # Use getattr with a default to avoid AttributeError
    existing_attrs = getattr(entity, '_attr_extra_state_attributes', None) or {}
    
    entity._attr_extra_state_attributes = {
        **existing_attrs,
        "protocol_settings": settings  # Just use a regular dict - HA will handle immutability
    }


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
        self._unsub_dispatcher = None

    def subscribe_to_entity_sync(self) -> None:
        """Subscribe to dispatcher signal for entity sync.

        This is needed because add_update_listener uses weak references
        and may not work if the manager object gets garbage collected.
        """
        @callback
        def _handle_sync_signal() -> None:
            """Handle entity sync signal."""
            _LOGGER.debug("[EntityManager] Received sync signal for %s (coordinator: %s)",
                         self._get_entity_type_suffix(),
                         getattr(self.coordinator, 'coordinator_key', 'unknown'))
            self.hass.async_create_task(self.sync_entities())

        signal = f"{SIGNAL_ENTITY_SYNC}_{self.entry.entry_id}"
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, signal, _handle_sync_signal
        )
        _LOGGER.debug("[EntityManager] Subscribed to signal %s for %s",
                     signal, self._get_entity_type_suffix())
    
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
        """Generate stable unique_id, including slave_id for multi-slave."""
        address = entity_config.get("address", "unknown")
        entity_type = entity_config.get("register_type") or entity_config.get("entity_type", "auto")
        suffix = self._get_entity_type_suffix()
        # Include entity name to handle multiple entities at same address
        name_key = self._entity_key(entity_config.get("name", "unknown"))
        # Include slave_id/device_index for multi-slave/multi-device to prevent collisions
        slave_prefix = ""
        if hasattr(self.coordinator, 'slave_id'):
            slave_prefix = f"s{self.coordinator.slave_id}_"
        elif hasattr(self.coordinator, 'device_index') and self.coordinator.device_index > 0:
            slave_prefix = f"d{self.coordinator.device_index}_"
        return f"{self.entry.entry_id}_{slave_prefix}{name_key}_{address}_{entity_type}_{suffix}"
    
    async def sync_entities(self) -> None:
        """Create, update, and remove entities based on current config."""
        _LOGGER.debug("[EntityManager] sync_entities called for %s, existing entities: %d",
                     self._get_entity_type_suffix(), len(self.entities))
        config_key = self._get_entities_config_key()

        # For Modbus, check if we have the new CONF_SLAVES structure
        protocol = self.entry.data.get(CONF_PROTOCOL, CONF_PROTOCOL_MODBUS)
        if protocol == CONF_PROTOCOL_MODBUS:
            slaves = self.entry.options.get(CONF_SLAVES, [])
            if slaves:
                # Multi-slave mode: get entities from coordinator's slave
                # The coordinator has slave_id and slave_index attributes set
                if hasattr(self.coordinator, 'slave_index'):
                    slave_index = self.coordinator.slave_index
                    if slave_index < len(slaves):
                        current_configs = slaves[slave_index].get('registers', [])
                        _LOGGER.debug("Reading entities from slave %d (index %d): %d entities",
                                     self.coordinator.slave_id, slave_index, len(current_configs))
                    else:
                        _LOGGER.warning("Slave index %d out of range (total slaves: %d)",
                                       slave_index, len(slaves))
                        current_configs = []
                else:
                    # Single slave mode (backward compatibility)
                    current_configs = slaves[0].get('registers', [])
                    _LOGGER.debug("Reading entities from single slave: %d entities", len(current_configs))
            else:
                # Old structure fallback
                current_configs = self.entry.options.get(config_key, [])
                _LOGGER.debug("Reading entities from old structure (%s): %d entities",
                             config_key, len(current_configs))
        elif protocol == CONF_PROTOCOL_BACNET:
            # BACnet multi-device mode: get entities from coordinator's device
            bacnet_devices = self.entry.options.get(CONF_BACNET_DEVICES, [])
            if bacnet_devices:
                # Multi-device mode: get entities from coordinator's device
                if hasattr(self.coordinator, 'device_index'):
                    device_index = self.coordinator.device_index
                    if device_index < len(bacnet_devices):
                        current_configs = bacnet_devices[device_index].get('entities', [])
                        _LOGGER.debug("Reading entities from BACnet device %d (index %d): %d entities",
                                     bacnet_devices[device_index].get('device_id'), device_index, len(current_configs))
                    else:
                        _LOGGER.warning("BACnet device index %d out of range (total devices: %d)",
                                       device_index, len(bacnet_devices))
                        current_configs = []
                else:
                    # Single device mode (backward compatibility)
                    current_configs = bacnet_devices[0].get('entities', [])
                    _LOGGER.debug("Reading entities from single BACnet device: %d entities", len(current_configs))
            else:
                # Old structure fallback (shouldn't happen after migration)
                current_configs = self.entry.options.get(CONF_ENTITIES, [])
                _LOGGER.debug("Reading entities from old BACnet structure: %d entities", len(current_configs))
        else:
            # Other protocols (SNMP, MQTT, etc.) use the config key directly
            current_configs = self.entry.options.get(config_key, [])

        desired_ids = set()
        new_entities: list[Entity] = []

        for config in current_configs:
            entity_name = config.get("name", "unknown")
            should_create = self._should_create_entity(config)
            _LOGGER.debug("[EntityManager] Processing config '%s': should_create=%s for %s",
                         entity_name, should_create, self._get_entity_type_suffix())
            if not should_create:
                continue

            unique_id = self._unique_id(config)
            desired_ids.add(unique_id)

            # Check if we already have this entity in memory
            if unique_id in self.entities:
                _LOGGER.debug("[EntityManager] Entity '%s' already exists in memory (uid=%s)", entity_name, unique_id)
                continue

            # Always create the entity - HA will merge with existing registry entry if present
            _LOGGER.debug("[EntityManager] Creating entity '%s' (uid=%s)", entity_name, unique_id)
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

        # Remove entities that are no longer in config (from our in-memory dict)
        for uid in list(self.entities):
            if uid not in desired_ids:
                entity = self.entities.pop(uid)
                if entity and entity.entity_id:
                    self.ent_reg.async_remove(entity.entity_id)
                    _LOGGER.debug("Removed entity %s", entity.entity_id)
                    await entity.async_remove()

        # Also clean up orphaned registry entries for this coordinator
        # This handles entities that exist in registry but not in our dict
        domain = self._get_entity_type_suffix()
        # Build prefix to match our coordinator's entities
        if hasattr(self.coordinator, 'slave_id'):
            uid_prefix = f"{self.entry.entry_id}_s{self.coordinator.slave_id}_"
        elif hasattr(self.coordinator, 'device_index') and self.coordinator.device_index > 0:
            uid_prefix = f"{self.entry.entry_id}_d{self.coordinator.device_index}_"
        else:
            uid_prefix = f"{self.entry.entry_id}_"
        uid_suffix = f"_{domain}"

        for entry in list(self.ent_reg.entities.values()):
            if (entry.platform == "protocol_wizard" and
                entry.unique_id and
                entry.unique_id.startswith(uid_prefix) and
                entry.unique_id.endswith(uid_suffix) and
                entry.unique_id not in desired_ids):
                _LOGGER.debug("Removing orphaned registry entry: %s (uid=%s)",
                             entry.entity_id, entry.unique_id)
                self.ent_reg.async_remove(entry.entity_id)
        
        _LOGGER.info(
            "%s sync complete — active=%d, defined=%d",
            self._get_entity_type_suffix().title(),
            len(self.entities),
            len([c for c in current_configs if self._should_create_entity(c)]),
        )
    
    async def handle_options_update(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Handle options update callback."""
        _LOGGER.debug("[EntityManager] handle_options_update called for %s (coordinator: %s)",
                     self._get_entity_type_suffix(),
                     getattr(self.coordinator, 'coordinator_key', 'unknown'))
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
        self._attr_device_info = device_info
        apply_common_entity_attributes(self, entity_config, hass=self.hass)
        set_readonly_protocol_settings(self, entity_config)
    
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
        
        # Defensive data_type (needed for write logic)
        self.data_type = entity_config.get("data_type", "uint16")
    
        # Get safe defaults based on data_type
        defaults = get_safe_number_defaults(self.data_type)
    
        # Use config values if provided, otherwise safe defaults
        self._attr_native_min_value = float(entity_config.get("min", defaults["min"]))
        self._attr_native_max_value = float(entity_config.get("max", defaults["max"]))
        self._attr_native_step = float(entity_config.get("step", defaults["step"]))
        
        apply_common_entity_attributes(self, entity_config, hass=self.hass)
        set_readonly_protocol_settings(self, entity_config)

    
    @property
    def native_value(self):
        return self.coordinator.data.get(self._key)

    @property
    def native_min_value(self) -> float:
        return self._attr_native_min_value

    @property
    def native_max_value(self) -> float:
        return self._attr_native_max_value

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
        self._attr_icon = "mdi:toggle-switch" # can be overwritten if there is an icon requested by config
        apply_common_entity_attributes(self, entity_config, hass=self.hass)
        set_readonly_protocol_settings(self, entity_config)


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
        apply_common_entity_attributes(self, entity_config, hass=self.hass)
        set_readonly_protocol_settings(self, entity_config)

        
        # Build value mapping from options dict
        options_raw = entity_config.get("options")
        
        # Normalize options:
        # - dict → OK
        # - JSON string → parse
        # - anything else → empty
        if isinstance(options_raw, str):
            try:
                options_dict = json.loads(options_raw)
            except Exception:
                _LOGGER.error(
                    "Invalid options JSON for %s: %r",
                    entity_config.get("name"),
                    options_raw,
                )
                options_dict = {}
        elif isinstance(options_raw, dict):
            options_dict = options_raw
        else:
            options_dict = {}
        
        # Final safety check
        if not isinstance(options_dict, dict):
            _LOGGER.error(
                "Options must be dict for %s, got %s",
                entity_config.get("name"),
                type(options_dict),
            )
            options_dict = {}
        
        self._value_map = {str(k): v for k, v in options_dict.items()}
        self._reverse_map = {v: k for k, v in self._value_map.items()}
        self._attr_options = list(self._reverse_map.keys())

    @property
    def current_option(self):
        raw = self.coordinator.data.get(self._key)
        if raw is None:
            return None

        raw_str = str(raw)

        # Check if raw value is already a mapped option label (coordinator pre-mapped it)
        if raw_str in self._reverse_map:
            return raw_str

        # Try to map raw value to option label
        if raw_str in self._value_map:
            return self._value_map[raw_str]

        # Handle float that's really an int (e.g., 1.0 -> "1")
        if isinstance(raw, float) and raw.is_integer():
            int_str = str(int(raw))
            if int_str in self._value_map:
                return self._value_map[int_str]

        return None
    
    async def async_select_option(self, option: str) -> None:
        """Write selected option to protocol."""
        _LOGGER.debug("async_select_option called: option=%s, entity=%s", option, self._config.get("name"))
        _LOGGER.debug("  _reverse_map=%s", self._reverse_map)

        value = self._reverse_map.get(option)
        if value is None:
            _LOGGER.warning("No reverse mapping for option: %s", option)
            return

        _LOGGER.debug("  reverse_map lookup: %s -> %s", option, value)

        if self._config.get("rw") not in ("write", "rw"):
            _LOGGER.warning(
                "Blocked write to read-only entity %s (rw=%s)",
                self._config.get("name"),
                self._config.get("rw"),
            )
            return

        # Protocol-specific value conversion
        protocol = self.coordinator.protocol_name
        _LOGGER.debug("  protocol=%s, data_type=%s", protocol, self._config.get("data_type"))
    
        try:
            if protocol == CONF_PROTOCOL_MQTT:
                # MQTT: Keep as string (payload)
                value = str(value)  # Ensure it's a string
    
            elif protocol == CONF_PROTOCOL_MODBUS:
                # Modbus: Convert to numeric (int/float)
                register_type = self._config.get("register_type", "holding").lower()
    
                if register_type in ("coil", "discrete"):
                    value = bool(int(float(value)))  # "0" → False, "1" → True
                elif "float" in self._config.get("data_type", ""):
                    value = float(value)
                else:
                    value = int(round(float(value)))  # Regular registers
    
            elif protocol == CONF_PROTOCOL_BACNET:
                # BACnet: convert based on data type
                data_type = self._config.get("data_type", "")
                if data_type in ("enum", "enumerated", "unsigned"):
                    # Value is the key from reverse_map (e.g., "2"), convert to int
                    try:
                        value = int(value)
                    except (ValueError, TypeError):
                        _LOGGER.warning("Could not convert %s to int for BACnet enum", value)
                elif data_type == "boolean":
                    # Value is "active" or "inactive" from reverse_map, keep as string
                    pass
    
            else:
                # Other protocols: try numeric conversion as fallback
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    value = str(value)
    
            _LOGGER.debug("Writing value: %s (type: %s)", value, type(value))
    
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
    
        except Exception as err:
            _LOGGER.error("Error in async_select_option: %s", err)
            import traceback
            traceback.print_exc()

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
        # Include coordinator_key in unique_id for multi-slave/multi-device
        coordinator_key = getattr(coordinator, 'coordinator_key', entry.entry_id)
        protocol = coordinator.protocol_name

        # Get slave/device identifier for multi-device scenarios
        slave_id = getattr(coordinator, 'slave_id', None)
        device_index = getattr(coordinator, 'device_index', None)

        # Build unique_id that includes protocol for uniqueness
        self._attr_unique_id = f"{coordinator_key}_{protocol}_hub"
        self._attr_name = f"{protocol.title()} Hub"

        # CRITICAL: Set suggested_object_id to ensure entity_id ends with _{protocol}_hub
        # This is required for the frontend card's protocol detection (_getProtocol)
        # which checks if entity_id ends with "_modbus_hub", "_snmp_hub", etc.
        if slave_id is not None:
            # Modbus multi-slave: include slave_id for unique entity_id
            self._attr_suggested_object_id = f"slave_{slave_id}_{protocol}_hub"
        elif device_index is not None:
            # BACnet/other multi-device: include device_index
            self._attr_suggested_object_id = f"device_{device_index}_{protocol}_hub"
        else:
            # Single device mode: just protocol_hub
            self._attr_suggested_object_id = f"{protocol}_hub"

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
            _LOGGER.debug("Failed to get hub status: %s", err)
            return "unknown"


class ModbusSlaveIdEntity(CoordinatorEntity, SensorEntity):
    """Diagnostic entity showing the Modbus slave ID."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:identifier"

    def __init__(
        self,
        coordinator: BaseProtocolCoordinator,
        entry: ConfigEntry,
        device_info: DeviceInfo,
    ):
        super().__init__(coordinator)
        coordinator_key = getattr(coordinator, 'coordinator_key', entry.entry_id)
        slave_id = getattr(coordinator, 'slave_id', 1)

        self._attr_unique_id = f"{coordinator_key}_slave_id"
        self._attr_name = "Slave ID"
        self._attr_suggested_object_id = f"slave_{slave_id}_slave_id"
        self._attr_device_info = device_info
        self._slave_id = slave_id

    @property
    def native_value(self):
        return self._slave_id


class ModbusConnectionInfoEntity(CoordinatorEntity, SensorEntity):
    """Diagnostic entity showing Modbus connection info (baud rate for serial, host:port for TCP)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:serial-port"

    def __init__(
        self,
        coordinator: BaseProtocolCoordinator,
        entry: ConfigEntry,
        device_info: DeviceInfo,
    ):
        super().__init__(coordinator)
        coordinator_key = getattr(coordinator, 'coordinator_key', entry.entry_id)
        slave_id = getattr(coordinator, 'slave_id', None)

        self._attr_unique_id = f"{coordinator_key}_connection_info"
        self._attr_name = "Connection Info"
        if slave_id is not None:
            self._attr_suggested_object_id = f"slave_{slave_id}_connection_info"
        else:
            self._attr_suggested_object_id = "connection_info"
        self._attr_device_info = device_info
        self._entry = entry

        # Determine connection type and build info string
        connection_type = entry.data.get("connection_type", "serial")
        if connection_type == "serial":
            self._attr_icon = "mdi:serial-port"
            port = entry.data.get("serial_port", "unknown")
            baudrate = entry.data.get("baudrate", 9600)
            parity = entry.data.get("parity", "N")
            stopbits = entry.data.get("stopbits", 1)
            bytesize = entry.data.get("bytesize", 8)
            self._connection_info = f"{baudrate} {bytesize}{parity}{stopbits}"
            self._attr_extra_state_attributes = {
                "connection_type": "serial",
                "port": port,
                "baudrate": baudrate,
                "parity": parity,
                "stopbits": stopbits,
                "bytesize": bytesize,
            }
        else:
            self._attr_icon = "mdi:ethernet"
            host = entry.data.get("host", "unknown")
            port = entry.data.get("port", 502)
            ip_type = entry.data.get("ip", "TCP")
            self._connection_info = f"{host}:{port} ({ip_type})"
            self._attr_extra_state_attributes = {
                "connection_type": ip_type.lower(),
                "host": host,
                "port": port,
            }

    @property
    def native_value(self):
        return self._connection_info


def get_all_coordinators_for_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Get all coordinators for a config entry with their device infos.

    Returns list of (coordinator, device_info) tuples.
    Handles multi-slave Modbus and multi-device BACnet.
    """
    from .const import DOMAIN, CONF_SLAVES, CONF_PROTOCOL, CONF_PROTOCOL_MODBUS
    from homeassistant.helpers.entity import DeviceInfo

    coordinator_keys = hass.data[DOMAIN].get("entry_coordinator_keys", {}).get(
        entry.entry_id, [entry.entry_id]
    )
    result = []
    for key in coordinator_keys:
        coordinator = hass.data[DOMAIN]["coordinators"].get(key)
        if coordinator:
            device_identifier = getattr(coordinator, 'coordinator_key', key)

            # Build device name with slave/device context
            hub_name = entry.title or f"{coordinator.protocol_name.title()} Device"
            device_name = hub_name

            # For Modbus, include slave name
            if entry.data.get(CONF_PROTOCOL) == CONF_PROTOCOL_MODBUS:
                slaves = entry.options.get(CONF_SLAVES, [])
                slave_idx = getattr(coordinator, 'slave_index', 0)
                if slaves and slave_idx < len(slaves):
                    slave_info = slaves[slave_idx]
                    slave_name = slave_info.get("name", f"Slave {slave_info.get('slave_id', slave_idx + 1)}")
                    device_name = f"{hub_name} - {slave_name}"

            device_info = DeviceInfo(
                identifiers={(DOMAIN, device_identifier)},
                name=device_name,
                manufacturer=coordinator.protocol_name.title(),
                model="Protocol Wizard",
            )
            result.append((coordinator, device_info))
    return result
