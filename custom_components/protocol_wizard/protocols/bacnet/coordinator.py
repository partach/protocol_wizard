# protocols/bacnet/coordinator.py
"""BACnet coordinator for Protocol Wizard."""

import logging
from typing import Any
import asyncio
from datetime import timedelta
from .. import ProtocolRegistry
from ...protocols.base import BaseProtocolCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .const import parse_bacnet_address, entity_key
from .client import BACnetClient
from ...const import CONF_ENTITIES, CONF_PROTOCOL_BACNET, CONF_BACNET_DEVICES
_LOGGER = logging.getLogger(__name__)

@ProtocolRegistry.register(CONF_PROTOCOL_BACNET)
class BACnetCoordinator(BaseProtocolCoordinator):
    """BACnet data coordinator for Protocol Wizard."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: BACnetClient,
        config_entry: ConfigEntry,
        update_interval: timedelta,
    ):
        """Initialize BACnet coordinator."""
        super().__init__(
            hass=hass,
            client=client,
            config_entry=config_entry,
            update_interval=update_interval,
            name="BACnet Monitor",
        )
        self.protocol_name = CONF_PROTOCOL_BACNET
        self._lock = asyncio.Lock()
    
    async def async_read_entity(
        self,
        address: str,
        entity_config: dict,
        **kwargs,
    ) -> Any | None:
        """
        Read a single entity value (required by base class).
        
        Args:
            entity_config: Entity configuration dict
            
        Returns:
            The entity_config value or None if read failed
        """
        try:
            # Parse BACnet address: "analogInput:0:presentValue"
            if not address:
                address = entity_config.get("address")
            if not address:
                _LOGGER.warning("Entity %s has no address", entity_config.get("name"))
                return None
            
            object_type, instance, property_name = parse_bacnet_address(address)
            
            # Read property value
            result = await self.client.read_property(
                object_type,
                instance,
                property_name
            )
            
            if result is None:
                _LOGGER.debug(
                    "Failed to read %s for entity %s",
                    address,
                    entity_config.get("name")
                )
                return None
            
            # Decode and format value
            decoded = self._decode_value(result, entity_config)
            formatted = self._format_value(decoded, entity_config)
            
            return formatted
            
        except ValueError as err:
            _LOGGER.error(
                "Invalid address format for entity %s: %s",
                entity_config.get("name"),
                err
            )
            return None
            
        except Exception as err:
            _LOGGER.error(
                "Error reading entity %s: %s",
                entity_config.get("name"),
                err
            )
            return None
    
    
    async def async_write_entity(
        self,
        address: str,
        value: Any,
        entity_config: dict,
        **kwargs,
    ) -> bool:
        """
        Write a value to an entity (required by base class).

        Args:
            entity_config: Entity configuration dict
            value: Value to write

        Returns:
            True if write successful, False otherwise
        """
        try:
            _LOGGER.debug("async_write_entity called: address=%s, value=%s, entity=%s",
                         address, value, entity_config.get("name"))

            # Parse address
            if not address:
                address = entity_config.get("address")
            object_type, instance, property_name = parse_bacnet_address(address)

            _LOGGER.debug("Parsed address: %s, %s, %s", object_type, instance, property_name)

            # Encode value (reverse scale/offset, type conversion)
            write_value = self._encode_value(value, entity_config)

            # Write to BACnet device (default priority 8)
            priority = entity_config.get("priority", 8)
            _LOGGER.debug("Calling write_property: %s,%s.%s = %s (priority %d)",
                         object_type, instance, property_name, write_value, priority)

            success = await self.client.write_property(
                object_type,
                instance,
                property_name,
                write_value,
                priority
            )

            if success:
                _LOGGER.info("Wrote %s to %s (priority %d)",
                           write_value, entity_config.get("name"), priority)
            else:
                _LOGGER.error("Write failed for %s (no exception but returned False)",
                            entity_config.get("name"))

            return success

        except ValueError as err:
            _LOGGER.error("Invalid address for entity %s: %s", entity_config.get("name"), err)
            return False

        except Exception as err:
            _LOGGER.error("Write error for entity %s: %s", entity_config.get("name"), err)
            import traceback
            _LOGGER.error(traceback.format_exc())
            return False
    
    
    def _encode_value(self, value: Any, entity_config: dict) -> Any:
        """
        Encode value for BACnet write (reverse of _decode_value).

        Args:
            value: Value from Home Assistant
            entity_config: Entity configuration dict

        Returns:
            Encoded value ready for BACnet write
        """
        write_value = value
        data_type = entity_config.get("data_type", "float")

        _LOGGER.debug("Encoding value: %s (type: %s) for data_type: %s",
                     value, type(value).__name__, data_type)

        # Reverse scale/offset for numeric values
        if isinstance(value, (int, float)) and data_type not in ("boolean", "string"):
            offset = float(entity_config.get("offset", 0.0))
            scale = float(entity_config.get("scale", 1.0))

            # Reverse: (value - offset) / scale
            if offset != 0.0:
                write_value = write_value - offset
            if scale != 1.0 and scale != 0:
                write_value = write_value / scale

        # Type conversion based on data_type
        try:
            if data_type == "integer":
                write_value = int(write_value)
            elif data_type == "float":
                write_value = float(write_value)
            elif data_type == "boolean":
                # BACnet binary values need "active"/"inactive" strings
                if isinstance(write_value, str) and write_value in ("active", "inactive"):
                    pass  # Keep as string
                elif write_value in (True, 1, "1", "true", "True", "on", "On"):
                    write_value = "active"
                else:
                    write_value = "inactive"
            elif data_type == "string":
                write_value = str(write_value)
            elif data_type in ("enumerated", "unsigned", "enum"):
                write_value = int(write_value)
        except (ValueError, TypeError) as err:
            _LOGGER.warning(
                "Type conversion failed for %s (type: %s): %s",
                entity_config.get("name"),
                data_type,
                err
            )
            return value  # Return original if conversion fails

        _LOGGER.debug("Encoded value: %s (type: %s)", write_value, type(write_value).__name__)
        
        return write_value
    
    
    # ----------------------------------------------------------------
    # BaseProtocolCoordinator Implementation
    # ----------------------------------------------------------------
    
    async def _async_update_data(self) -> dict[str, Any]:
        """
        Fetch latest data from configured BACnet entities.
        
        Returns:
            Dict of entity data keyed by entity name
        """
        # Check connection
        if not await self._async_connect():
            _LOGGER.warning("[BACnet] Could not connect to device — skipping update")
            return {}
        
        # Get entities from config (multi-device structure)
        bacnet_devices = self.my_config_entry.options.get(CONF_BACNET_DEVICES, [])
        _LOGGER.info("[BACnet] _async_update_data: has device_index=%s, bacnet_devices count=%d",
                    hasattr(self, 'device_index'), len(bacnet_devices))

        if bacnet_devices and hasattr(self, 'device_index'):
            # Multi-device mode: get entities from this device
            device_index = self.device_index
            if device_index < len(bacnet_devices):
                entities = bacnet_devices[device_index].get('entities', [])
                _LOGGER.info("[BACnet] Loaded %d entities from device_index %d", len(entities), device_index)
            else:
                _LOGGER.warning("[BACnet] Device index %d out of range (total: %d)",
                              device_index, len(bacnet_devices))
                entities = []
        else:
            # Fallback to old structure for backward compatibility
            entities = self.my_config_entry.options.get(CONF_ENTITIES, [])
            _LOGGER.info("[BACnet] Fallback: loaded %d entities from CONF_ENTITIES", len(entities))

        if not entities:
            _LOGGER.warning("[BACnet] No entities configured for this device")
            return {}
        
        new_data = {}
        failed_count = 0
        
        async with self._lock:
            for entity in entities:
                try:
                    # Parse BACnet address: "analogInput:0:presentValue"
                    address = entity.get("address")
                    if not address:
                        _LOGGER.warning("Entity %s has no address", entity.get("name"))
                        continue
                    
                    object_type, instance, property_name = parse_bacnet_address(address)
                    
                    # Read property value
                    result = await self.client.read_property(
                        object_type,
                        instance,
                        property_name
                    )
                    
                    if result is None:
                        failed_count += 1
                        _LOGGER.debug(
                            "Failed to read %s for entity %s",
                            address,
                            entity.get("name")
                        )
                        continue
                    
                    # Generate entity key
                    key = entity_key(entity["name"])
                    
                    # Decode and format value
                    decoded = self._decode_value(result, entity)
                    formatted = self._format_value(decoded, entity)
                    
                    new_data[key] = formatted
                    
                except ValueError as err:
                    _LOGGER.error(
                        "Invalid address format for entity %s: %s",
                        entity.get("name"),
                        err
                    )
                    failed_count += 1
                    
                except Exception as err:
                    _LOGGER.error(
                        "Error reading entity %s: %s",
                        entity.get("name"),
                        err
                    )
                    failed_count += 1
        
        # Log summary
        if failed_count > 0:
            _LOGGER.info(
                "[BACnet] Update complete — success: %d, failed: %d",
                len(new_data),
                failed_count
            )
        
        return new_data
    
    
    async def _async_connect(self) -> bool:
        """
        Ensure connection to BACnet device.
        
        Returns:
            True if connected, False otherwise
        """
        if self.client.connected:
            return True
        
        try:
            connected = await self.client.connect()
            if connected:
                _LOGGER.info("[BACnet] Connected to device")
                return True
            else:
                _LOGGER.warning("[BACnet] Connection failed")
                return False
        except Exception as err:
            _LOGGER.error("[BACnet] Connection error: %s", err)
            return False
    
    
    def _decode_value(self, raw_value: Any, entity_config: dict) -> Any:
        """
        Decode BACnet value with type conversion, scale, and offset.

        Args:
            raw_value: Raw value from BACnet read
            entity_config: Entity configuration dict

        Returns:
            Decoded value (raw, not mapped to options labels)
        """
        value = raw_value
        data_type = entity_config.get("data_type", "float")

        # Type conversion based on data_type
        try:
            if data_type == "float":
                value = float(value)
            elif data_type == "integer":
                value = int(value)
            elif data_type == "boolean":
                # Keep string values like "active"/"inactive" for select entity mapping
                if isinstance(value, str) and value.lower() in ("active", "inactive"):
                    pass  # Keep as string for options mapping in select entity
                elif isinstance(value, bool):
                    pass
                elif isinstance(value, (int, float)):
                    value = bool(value)
                elif isinstance(value, str):
                    value = value.lower() in ("true", "1", "on", "active", "yes")
                else:
                    value = bool(value)
            elif data_type == "string":
                value = str(value)
            elif data_type in ("enumerated", "unsigned"):
                value = int(value)
        except (ValueError, TypeError) as err:
            _LOGGER.warning(
                "Type conversion failed for %s (type: %s): %s",
                entity_config.get("name"),
                data_type,
                err
            )
            return raw_value

        # Apply scale and offset for numeric types
        if isinstance(value, (int, float)) and data_type != "boolean":
            scale = float(entity_config.get("scale", 1.0))
            offset = float(entity_config.get("offset", 0.0))

            if scale != 1.0:
                value = value * scale
            if offset != 0.0:
                value = value + offset

        return value
    
    
    def _format_value(self, decoded_value: Any, entity_config: dict) -> Any:
        """
        Format decoded value with format string.
        
        Args:
            decoded_value: Decoded value
            entity_config: Entity configuration dict
        
        Returns:
            Formatted value
        """
        format_str = entity_config.get("format", "")
        
        if format_str and isinstance(decoded_value, (int, float)):
            try:
                return format_str.format(decoded_value)
            except (ValueError, KeyError) as err:
                _LOGGER.warning(
                    "Format string error for %s: %s",
                    entity_config.get("name"),
                    err
                )
        
        return decoded_value
    
    
    # ----------------------------------------------------------------
    # Write Support
    # ----------------------------------------------------------------
    
    async def async_write_value(
        self,
        entity_name: str,
        value: Any,
        priority: int = 8
    ) -> bool:
        """
        Write value to BACnet entity.
        
        Args:
            entity_name: Name of entity to write
            value: Value to write
            priority: BACnet write priority (1-16, default 8)
        
        Returns:
            True if write successful, False otherwise
        """
        # Find entity config
        entities = self.my_config_entry.options.get(CONF_ENTITIES, [])
        entity_config = None
        
        for entity in entities:
            if entity.get("name") == entity_name:
                entity_config = entity
                break
        
        if not entity_config:
            _LOGGER.error("Entity %s not found", entity_name)
            return False
        
        # Check if entity is writable
        rw = entity_config.get("rw", "read")
        if rw not in ("write", "rw"):
            _LOGGER.error("Entity %s is not writable (rw=%s)", entity_name, rw)
            return False
        
        try:
            # Parse address
            address = entity_config.get("address")
            object_type, instance, property_name = parse_bacnet_address(address)
            
            # Reverse scale/offset for numeric values
            write_value = value
            data_type = entity_config.get("data_type", "float")
            
            if isinstance(value, (int, float)) and data_type != "boolean":
                offset = float(entity_config.get("offset", 0.0))
                scale = float(entity_config.get("scale", 1.0))
                
                # Reverse: (value - offset) / scale
                if offset != 0.0:
                    write_value = write_value - offset
                if scale != 1.0 and scale != 0:
                    write_value = write_value / scale
            
            # Type conversion
            if data_type == "integer":
                write_value = int(write_value)
            elif data_type == "float":
                write_value = float(write_value)
            elif data_type == "boolean":
                write_value = bool(write_value)
            elif data_type == "string":
                write_value = str(write_value)
            
            # Write to BACnet device
            success = await self.client.write_property(
                object_type,
                instance,
                property_name,
                write_value,
                priority
            )
            
            if success:
                _LOGGER.info(
                    "Wrote %s to %s (priority %d)",
                    write_value,
                    entity_name,
                    priority
                )
                
                # Trigger immediate update to reflect change
                await self.async_request_refresh()
            else:
                _LOGGER.error("Write failed for %s", entity_name)
            
            return success
        
        except ValueError as err:
            _LOGGER.error("Invalid address for entity %s: %s", entity_name, err)
            return False
        
        except Exception as err:
            _LOGGER.error("Write error for entity %s: %s", entity_name, err)
            return False
    
    
    # ----------------------------------------------------------------
    # Utility Methods
    # ----------------------------------------------------------------
    
    def _entity_key(self, name: str) -> str:
        """
        Generate consistent key from entity name.
        
        Args:
            name: Entity name
        
        Returns:
            Lowercase key with underscores
        """
        return entity_key(name)
