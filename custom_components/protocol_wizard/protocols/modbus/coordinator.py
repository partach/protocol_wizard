#------------------------------------------
#-- protocol modbus coordinator.py protocol wizard
#------------------------------------------
"""Modbus protocol coordinator implementation."""
from __future__ import annotations

import logging
import asyncio
from typing import Any
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from pymodbus.client.mixin import ModbusClientMixin
from .client import ModbusClient

from ..base import BaseProtocolCoordinator
from .. import ProtocolRegistry
from .const import TYPE_SIZES, reg_key
from ...const import CONF_REGISTERS,CONF_SLAVES

_LOGGER = logging.getLogger(__name__)

# Reduce noise from pymodbus - TEMPORARILY COMMENTED FOR DEBUG
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
logging.getLogger("pymodbus.logging").setLevel(logging.CRITICAL)
# logging.getLogger("homeassistant.helpers.update_coordinator").setLevel(logging.CRITICAL)

@ProtocolRegistry.register("modbus")
class ModbusCoordinator(BaseProtocolCoordinator):
    """Modbus protocol coordinator."""
    
    def __init__(
        self,
        hass: HomeAssistant,
        client: ModbusClient,
        config_entry: ConfigEntry,
        update_interval: timedelta,
    ):
        """Initialize Modbus coordinator."""
        super().__init__(
            hass=hass,
            client=client,
            config_entry=config_entry,
            update_interval=update_interval,
            name="Modbus Wizard",
        )
        
        self.protocol_name = "modbus"
        self._lock = asyncio.Lock()

    # ----------------------------------------------------------------
    # Connection Management with Recovery
    # ----------------------------------------------------------------
    async def _async_connect_unlocked(self) -> bool:
        """
        Ensure client is connected, with automatic recovery after errors.
        MUST be called while holding self._lock to prevent race conditions.
        """
        # Check if reconnection is needed due to previous errors (shared across all slaves)
        if self.client.needs_reconnect:
            slave_id = getattr(self, 'slave_id', '?')
            _LOGGER.info("[Modbus] Shared connection recovery needed (triggered by slave %s poll), attempting reconnect...", slave_id)
            return await self.client.reconnect()

        # Check if already connected
        if self.client.is_connected:
            return True

        # Need to connect
        try:
            return await self.client.connect()
        except Exception as err:
            _LOGGER.error("[Modbus] Failed to connect: %s", err)
            return False

    async def _async_connect(self) -> bool:
        """
        Ensure client is connected (acquires lock internally).
        For use by _async_update_data which handles its own locking for reads.
        """
        # Fast path: if connected and healthy, return immediately (no lock needed)
        if self.client.is_connected and not self.client.needs_reconnect:
            return True

        # Need to do connection work - acquire the bus lock
        async with self._lock:
            return await self._async_connect_unlocked()

    # ----------------------------------------------------------------
    # BaseProtocolCoordinator Implementation
    # ----------------------------------------------------------------
    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from configured entities."""

        # Get entities for THIS SPECIFIC SLAVE
        # Check if we have slave_id set (multi-slave mode)
        if hasattr(self, 'slave_id') and hasattr(self, 'slave_index'):
            # Multi-slave mode: read from this slave's register list
            slaves = self.my_config_entry.options.get(CONF_SLAVES, [])
            if slaves and self.slave_index < len(slaves):
                entities = slaves[self.slave_index].get('registers', [])
                _LOGGER.debug("Loaded %d entities for slave %d (index %d)",
                             len(entities), self.slave_id, self.slave_index)
            else:
                _LOGGER.warning("Slave index %d not found, total slaves: %d",
                               self.slave_index, len(slaves))
                entities = []
        else:
            # Backward compatibility: single slave mode, read from global CONF_REGISTERS
            entities = self.my_config_entry.options.get(CONF_REGISTERS, [])
            _LOGGER.debug("Loaded %d entities from CONF_REGISTERS (backward compat)", len(entities))

        if not entities:
            _LOGGER.debug("No entities to read")
            # Still attempt to connect so hub entity can report accurate status
            async with self._lock:
                await self._async_connect_unlocked()
            return {}

        new_data = {}
        failed_count = 0
        consecutive_failures = 0
        max_consecutive_failures = 2
        # Also limit total failures to prevent long update cycles
        max_total_failures = min(5, max(2, len(entities) // 3))

        # Single lock acquisition for entire update cycle: connect + all reads
        async with self._lock:
            if not await self._async_connect_unlocked():
                _LOGGER.warning("[Modbus] Could not connect to device — skipping update")
                return {}
            for entity in entities:
                # Early abort if device is clearly dead (consecutive failures)
                if consecutive_failures >= max_consecutive_failures:
                    _LOGGER.warning(
                        "[Modbus] Too many consecutive failures (%d) — aborting update cycle",
                        max_consecutive_failures
                    )
                    await self.client.disconnect()
                    break

                # Also abort if too many total failures (even if not consecutive)
                if failed_count >= max_total_failures:
                    _LOGGER.warning(
                        "[Modbus] Too many total failures (%d/%d) — aborting update cycle",
                        failed_count, len(entities)
                    )
                    break

                result = await self._read_entity(entity)
                if result is None:
                    failed_count += 1
                    consecutive_failures += 1
                    continue

                consecutive_failures = 0  # reset on success
                key = reg_key(entity["name"])
                decoded = self._decode_value(result.values, entity)
                formatted = self._format_value(decoded, entity)
                new_data[key] = formatted

        # Log if there were failures
        if failed_count > 0:
            _LOGGER.info("[Modbus] Update completed with %d/%d failures", failed_count, len(entities))

        return new_data

    async def _read_entity(self, entity: dict) -> Any | None:
        """Read one entity — handles auto-detect and direct read."""
        address = int(entity["address"])
        count = int(TYPE_SIZES.get(entity["data_type"].lower(), 1))
        reg_type = entity.get("register_type", "holding")

        # Debug: verify coordinator and client slave_id match
        coordinator_slave = getattr(self, 'slave_id', '?')
        client_slave = self.client.slave_id
        if coordinator_slave != '?' and int(coordinator_slave) != int(client_slave):
            _LOGGER.error("[Modbus] SLAVE ID MISMATCH! coordinator.slave_id=%s but client.slave_id=%s",
                         coordinator_slave, client_slave)

        # Auto-detect
        if reg_type == "auto":
            detected = await self._auto_detect_type(address, count)
            if detected is None:
                return None
            reg_type, result = detected
            entity["register_type"] = reg_type
        else:
            result = await self._direct_read(reg_type, address, count)

        if result is None or result.isError():
            return None

        # Extract values
        if reg_type in ("coil", "discrete"):
            values = result.bits[:count]
        else:
            values = result.registers[:count]

        if not values:
            _LOGGER.warning("Empty response for '%s'", entity["name"])
            return None

        return type("ReadResult", (), {"values": values})()

    async def _auto_detect_type(self, address: int, count: int) -> tuple[str, Any] | None:
        """Try different register types until one succeeds."""
        methods = [
            ("holding", self.client.raw_client.read_holding_registers),
            ("input", self.client.raw_client.read_input_registers),
            ("coil", self.client.raw_client.read_coils),
            ("discrete", self.client.raw_client.read_discrete_inputs),        
        ]

        for name, method in methods:
            try:
                result = await method(address=address, count=count, device_id=self.client.slave_id)
                if not result.isError():
                    return name, result
            except Exception:
                continue

        _LOGGER.warning("Auto-detect failed at address %d", address)
        return None

    async def _direct_read(self, reg_type: str, address: int, count: int) -> Any | None:
        """Perform direct read for known register type."""
        method_map = {
            "holding": self.client.raw_client.read_holding_registers,
            "input": self.client.raw_client.read_input_registers,
            "coil": self.client.raw_client.read_coils,
            "discrete": self.client.raw_client.read_discrete_inputs,
        }

        method = method_map.get(reg_type)
        if method is None:
            _LOGGER.error("Unknown register_type '%s'", reg_type)
            return None

        try:
            return await method(address=address, count=count, device_id=self.client.slave_id)
        except Exception as err:
            _LOGGER.error("Direct read failed for type %s: %s", reg_type, err)
            return None
    
   
    def _decode_value(self, raw_value: Any, entity_config: dict) -> Any | None:
        values = raw_value
        if not values:
            return None

        try:
            data_type = entity_config.get("data_type", "uint16").lower()
            word_order = entity_config.get("word_order", "big")

            if isinstance(values[0], bool):
                if len(values) == 1:
                    return bool(values[0])
                return int("".join("1" if b else "0" for b in values[::-1]), 2)

            expected = TYPE_SIZES.get(data_type, 1)
            if len(values) < expected:
                return None
            values = values[:expected]

            dt_map = {
                "uint16": ModbusClientMixin.DATATYPE.UINT16,
                "int16": ModbusClientMixin.DATATYPE.INT16,
                "uint32": ModbusClientMixin.DATATYPE.UINT32,
                "int32": ModbusClientMixin.DATATYPE.INT32,
                "float32": ModbusClientMixin.DATATYPE.FLOAT32,
                "uint64": ModbusClientMixin.DATATYPE.UINT64,
                "int64": ModbusClientMixin.DATATYPE.INT64,
                "string": ModbusClientMixin.DATATYPE.STRING,
            }
            target_type = dt_map.get(data_type, ModbusClientMixin.DATATYPE.UINT16)

            decoded = self.client.raw_client.convert_from_registers(
                registers=values,
                data_type=target_type,
                word_order=0 if word_order.lower() == "big" else 1,
            )

            if data_type == "float32" and isinstance(decoded, float):
                decoded = round(decoded, 6)
            if data_type == "string" and isinstance(decoded, str):
                decoded = decoded.rstrip("\x00")

            if isinstance(decoded, (int, float)):
                scale = entity_config.get("scale", 1)
                offset = entity_config.get("offset", 0)
                decoded = decoded * scale + offset

                # Preserve integer type for integer data types when result is whole number
                if data_type in ("uint16", "int16", "uint32", "int32", "uint64", "int64"):
                    if isinstance(decoded, float) and decoded.is_integer():
                        decoded = int(decoded)

            return decoded

        except Exception as err:
            _LOGGER.error(
                "Error decoding register '%s' at address %s: %s",
                entity_config.get("name"), entity_config.get("address"), err
            )
            return None
    
    def _encode_value(self, value: Any, entity_config: dict) -> list[int] | bool | None:
        """Encode value for write – full string support for Wizard card/service."""
        try:
            data_type = entity_config.get("data_type", "uint16").lower()
            register_type = entity_config.get("register_type", "holding").lower()
            word_order = entity_config.get("word_order", "big").lower()
        
            # _LOGGER.debug("Encoding started: value=%r (type=%s), data_type=%s, register_type=%s", value, type(value).__name__, data_type, register_type)
        
            # Coil handling – accept strings
            if register_type == "coil":
                if isinstance(value, str):
                    stripped = value.strip().lower()
                    if stripped in ("true", "1", "on", "yes"):
                        return True
                    if stripped in ("false", "0", "off", "no"):
                        return False
                    _LOGGER.error("Invalid coil value '%s' – use true/false, 1/0, on/off", value)
                    return None
                return bool(value)
        
            # Numeric registers – handle string input including true/false
            original_value = value
            if isinstance(value, str):
                stripped = value.strip().lower()
                if stripped in ("true", "1", "on", "yes"):
                    value = 1.0
                elif stripped in ("false", "0", "off", "no"):
                    value = 0.0
                else:
                    try:
                        value = float(value)
                    except ValueError:
                        _LOGGER.error("Cannot convert string '%s' to number for data_type %s", original_value, data_type)
                        return None
        
            # Apply reverse scale/offset
            scale = entity_config.get("scale", 1.0)
            offset = entity_config.get("offset", 0.0)
            if scale != 0:
                try:
                    value = (value - offset) / scale
                except Exception as err:
                    _LOGGER.error("Scale/offset failed for value %s: %s", original_value, err)
                    return None
        
            # Single register integer
            if data_type in ("uint16", "int16"):
                try:
                    value = int(round(float(value)))
                except Exception:
                    _LOGGER.error("Failed to convert to int for %s: %s", data_type, original_value)
                    return None
                if data_type == "int16" and value < 0:
                    value += 65536
                value = max(0, min(65535, value))
                return [value]
        except Exception as err:
            _LOGGER.error("Encoding error %s (%s): %s", value, data_type, err)
            return None    
        # Multi-register types
        dt_map = {
            "uint32": ModbusClientMixin.DATATYPE.UINT32,
            "int32": ModbusClientMixin.DATATYPE.INT32,
            "float32": ModbusClientMixin.DATATYPE.FLOAT32,
            "uint64": ModbusClientMixin.DATATYPE.UINT64,
            "int64": ModbusClientMixin.DATATYPE.INT64,
        }
        target_type = dt_map.get(data_type, ModbusClientMixin.DATATYPE.UINT16)
    
        if target_type == ModbusClientMixin.DATATYPE.FLOAT32:
            value = float(value)
        else:
            value = int(round(float(value)))
    
        try:
            return self.client.raw_client.convert_to_registers(
                value=value,
                data_type=target_type,
                word_order=0 if word_order == "big" else 1,
            )
        except Exception as err:
            _LOGGER.error("pymodbus convert_to_registers failed for %s (%s): %s", original_value, data_type, err)
            return None
    # ----------------------------------------------------------------------------
    # the service read method (naming a bit close to later refactoring above...
    #------------------------------------------------------------------------------
    
    async def async_read_entity(self, address: str, entity_config: dict, **kwargs) -> Any | None:
        from pymodbus.exceptions import ModbusIOException

        addr = int(address)
        size = kwargs.get("size") or TYPE_SIZES.get(entity_config.get("data_type", "uint16").lower(), 1)
        reg_type = kwargs.get("register_type") or entity_config.get("register_type", "holding")
        raw = kwargs.get("raw", False)

        # Single lock acquisition for entire operation: connect + read
        # This prevents race conditions when multiple slaves share the same connection
        async with self._lock:
            # Check/repair connection while holding lock
            if not await self._async_connect_unlocked():
                return None

            values = None
            detected_type = reg_type

            try:
                # If explicitly not auto, just read once
                if reg_type != "auto":
                    values = await self.client.read(address=address, count=size, register_type=reg_type)

                else:
                    # Proper auto-detect: try in sensible order (same as bulk)
                    for test_type in ["holding", "input", "coil", "discrete"]:
                        try:
                            test_values = await self.client.read(address=address, count=size, register_type=test_type)
                            if test_values is not None:
                                values = test_values
                                detected_type = test_type
                                break
                        except ModbusIOException:
                            continue  # Try next type

            except ModbusIOException as err:
                _LOGGER.warning("[Modbus] I/O error reading address %s: %s - will attempt reconnect on next request", address, err)
                # Connection will be recovered on next _async_connect call
                return None

            if values is None or len(values) == 0:
                _LOGGER.warning("Read failed for address %s", address)
                return None

            # Raw mode for Wizard card debugging
            if raw:
                is_coil = isinstance(values[0], bool) if values else False
                return {
                    "value": bool(values[0]) if size == 1 else values,
                    "registers": list(values) if not is_coil else None,
                    "bits": [bool(v) for v in values] if is_coil else None,
                    "detected_type": detected_type,
                    "address": addr,
                    "size": size,
                }

            return self._decode_value(values, entity_config)
    
    async def async_write_entity(self, address: str, value: Any, entity_config: dict, **kwargs) -> bool:
        encoded_value = self._encode_value(value, entity_config)
        if encoded_value is None:
            _LOGGER.error("Write failed – encoding returned None for value %r", value)
            return False

        # Single lock acquisition for entire operation: connect + write
        async with self._lock:
            if not await self._async_connect_unlocked():
                _LOGGER.error("Write failed – could not connect to device")
                return False

            success = await self.client.write(
                address=address,
                value=encoded_value,
                register_type=entity_config.get("register_type", "holding"),
            )

            if not success:
                _LOGGER.error("client.write returned False – check device logs or connection")
        
        return success
