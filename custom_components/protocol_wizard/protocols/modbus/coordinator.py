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

from ..base import BaseProtocolCoordinator
from .. import ProtocolRegistry
from .client import ModbusClient
from .const import CONF_ENTITIES, TYPE_SIZES, reg_key

_LOGGER = logging.getLogger(__name__)

# Reduce noise from pymodbus
# Setting parent logger to CRITICAL to catch all sub-loggers
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
logging.getLogger("pymodbus.logging").setLevel(logging.CRITICAL)

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
    # BaseProtocolCoordinator Implementation
    # ----------------------------------------------------------------
    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from configured entities."""
        if not await self._async_connect():
            _LOGGER.warning("[Modbus] Could not connect to device — skipping update")
            return {}

        entities = self.my_config_entry.options.get(CONF_ENTITIES, [])
        if not entities:
            return {}

        new_data = {}
        failed_count = 0
        consecutive_failures = 0
        max_consecutive_failures = 2

        async with self._lock:
            for entity in entities:
                # Early abort if device is clearly dead
                if consecutive_failures >= max_consecutive_failures:
                    _LOGGER.warning(
                        "[Modbus] Too many consecutive failures (%d) — aborting update cycle",
                        max_consecutive_failures
                    )
                    await self.client.disconnect()
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

        # Optional final health check
        if failed_count > len(entities) // 2:
            _LOGGER.info("[Modbus] High failure rate (%d/%d) — will retry connection", failed_count, len(entities))

        return new_data

    async def _read_entity(self, entity: dict) -> Any | None:
        """Read one entity — handles auto-detect and direct read."""
        address = int(entity["address"])
        count = int(TYPE_SIZES.get(entity["data_type"].lower(), 1))
        reg_type = entity.get("register_type", "holding")

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
    
   
    def _decode_value(
        self,
        raw_value: Any,
        entity_config: dict,
    ) -> Any | None:
        """Decode Modbus registers/bits to Python values."""
        values = raw_value  # values is list[int] or list[bool]
        
        if not values:
            return None
        
        try:
            data_type = entity_config.get("data_type", "uint16").lower()
      #      byte_order = entity_config.get("byte_order", "big")  # not used...?
            word_order = entity_config.get("word_order", "big")
            
            # Handle bit-based registers
            if isinstance(values[0], bool):
                if len(values) == 1:
                    return bool(values[0])
                # Multi-bit → pack into integer
                return int("".join("1" if b else "0" for b in values[::-1]), 2)
            
            # Single register types
            if data_type in ("uint16", "int16") and len(values) == 1:
                decoded = values[0]
                if data_type == "int16" and decoded > 32767:
                    decoded = decoded - 65536
            else:
                # Multi-register types
                expected = TYPE_SIZES.get(data_type)
                if expected and len(values) != expected:
                    _LOGGER.warning(
                        "Register size mismatch for %s at addr %s: got %d, expected %d",
                        data_type, entity_config.get("address"), len(values), expected
                    )
                    if len(values) < expected:
                        return None
                    values = values[:expected]
                
                # Map data type to pymodbus enum
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
                
                try:
                    decoded = self.client.raw_client.convert_from_registers(
                        registers=values,
                        data_type=target_type,
                        word_order=0 if word_order.lower() == "big" else 1,
                    )
                except Exception as err:
                    _LOGGER.warning("Failed to decode %s as %s: %s", values, data_type, err)
                    return None
            
            # Post-processing
            if data_type == "float32" and isinstance(decoded, float):
                decoded = round(decoded, 6)
            if data_type == "string" and isinstance(decoded, str):
                decoded = decoded.rstrip("\x00")
            
            # Apply scale and offset
            if isinstance(decoded, (int, float)):
                scale = entity_config.get("scale", 1.0)
                offset = entity_config.get("offset", 0.0)
                decoded = decoded * scale + offset
            
            return decoded
            
        except Exception as err:
            _LOGGER.error(
                "Error decoding register '%s' at address %s: %s",
                entity_config.get("name"), entity_config.get("address"), err
            )
            return None
    
    def _encode_value(
        self,
        value: Any,
        entity_config: dict,
    ) -> list[int] | bool:
        """Encode Python value to Modbus registers."""
        data_type = entity_config.get("data_type", "uint16").lower()
  #      byte_order = entity_config.get("byte_order", "big")
        word_order = entity_config.get("word_order", "big")
        register_type = entity_config.get("register_type", "holding")
        # For coils, return boolean directly
        if register_type == "coil":
            return bool(value)
        # Reverse scale/offset
        scale = entity_config.get("scale", 1.0)
        offset = entity_config.get("offset", 0.0)
        if scale != 0 and isinstance(value, (int, float)):
            value = (value - offset) / scale
        
        # Single register types
        if data_type in ("uint16", "int16"):
            if isinstance(value, float):
                value = int(round(value))
            
            if data_type == "int16" and value < 0:
                value = value + 65536
            
            value = max(0, min(65535, value))
            return [value]
        
        # Multi-register types
        dt_map = {
            "uint32": ModbusClientMixin.DATATYPE.UINT32,
            "int32": ModbusClientMixin.DATATYPE.INT32,
            "float32": ModbusClientMixin.DATATYPE.FLOAT32,
            "uint64": ModbusClientMixin.DATATYPE.UINT64,
            "int64": ModbusClientMixin.DATATYPE.INT64,
        }
        target_type = dt_map.get(data_type, ModbusClientMixin.DATATYPE.UINT16)
        
        if target_type != ModbusClientMixin.DATATYPE.FLOAT32:
            if isinstance(value, float):
                value = int(round(value))
        else:
            value = float(value)
        
        try:
            return self.client.raw_client.convert_to_registers(
                value=value,
                data_type=target_type,
                word_order=0 if word_order.lower() == "big" else 1,
            )
        except Exception as err:
            _LOGGER.error("Failed to encode %s as %s: %s", value, data_type, err)
            return None
    
    async def async_read_entity(
        self,
        address: str,
        entity_config: dict,
        **kwargs
    ) -> Any | None:
        """Read a single Modbus entity (for services)."""
        if not await self._async_connect():
            return None
        
        addr = int(address)
        size = kwargs.get("size") or TYPE_SIZES.get(entity_config.get("data_type", "uint16").lower(), 1)
        reg_type = kwargs.get("register_type") or entity_config.get("register_type", "holding")
        raw = kwargs.get("raw", False)
        
        async with self._lock:
            try:
                detected_type = reg_type
                result = None
                values = None
                
                # ============================================================
                # AUTO-DETECT: Try different register types
                # ============================================================
                if reg_type == "auto":
                    methods = [
                        ("holding", self.client.raw_client.read_holding_registers),
                        ("input", self.client.raw_client.read_input_registers),
                        ("coil", self.client.raw_client.read_coils),
                        ("discrete", self.client.raw_client.read_discrete_inputs),
                    ]
                    
                    for name, method in methods:
                        try:
                            read_count = max(size, 8) if name in ("coil", "discrete") else size
                    
                            result = await method(
                                address=addr,
                                count=read_count,
                                device_id=int(self.client.slave_id),
                            )
                    
                            if result.isError():
                                continue
                    
                            if name in ("holding", "input") and hasattr(result, "registers"):
                                detected_type = name
                                values = result.registers[:size]
                                break
                    
                            if name in ("coil", "discrete") and hasattr(result, "bits"):
                                detected_type = name
                                values = result.bits[:size]
                                break
                        except Exception as err:
                            _LOGGER.debug("Auto-detect failed for %s at %d: %s", name, addr, err)
                            continue
                    
                    if values is None:
                        _LOGGER.warning("Auto-detect failed at address %s", addr)
                        return None
                
                # ============================================================
                # DIRECT READ: Known register type
                # ============================================================
                else:
                    method_map = {
                        "holding": self.client.raw_client.read_holding_registers,
                        "input": self.client.raw_client.read_input_registers,
                        "coil": self.client.raw_client.read_coils,
                        "discrete": self.client.raw_client.read_discrete_inputs,
                    }
                    method = method_map.get(reg_type)
                    if method is None:
                        _LOGGER.error("Invalid register_type: %s", reg_type)
                        return None
                    read_count = max(size, 2) if reg_type in ("coil", "discrete") else size      
                    try:
                        result = await method(
                            address=int(addr),
                            count=int(read_count),
                            device_id=int(self.client.slave_id),
                        )
                        
                        if result.isError():
                            _LOGGER.error("Read failed for %s register at %d: error response", reg_type, addr)
                            return None
                        
                        # Extract values based on register type
                        if reg_type in ("coil", "discrete"):
                            if hasattr(result, "bits"):
                                values = result.bits[:size]
                            else:
                                _LOGGER.error("Coil/discrete result missing 'bits' attribute")
                                return None
                        else:
                            if hasattr(result, "registers"):
                                values = result.registers[:size]
                            else:
                                _LOGGER.error("Register result missing 'registers' attribute")
                                return None
                                
                    except Exception as err:
                        _LOGGER.error("Read failed for %s register at %d: %s", reg_type, addr, err)
                        return None
                
                # ============================================================
                # RETURN LOGIC
                # ============================================================
                if values is None or len(values) == 0:
                    _LOGGER.warning("No values returned for address %s", addr)
                    return None
                
                # RAW MODE: Return raw register/bit values with metadata
                if raw:
                    if detected_type in ("coil", "discrete"):
                        return {
                            "value": bool(values[0]) if size == 1 else [bool(v) for v in values],
                            "bits": [bool(v) for v in values],
                            "detected_type": detected_type,
                            "address": addr,
                            "size": size,
                        }
                    else:
                        return {
                            "value": values[0] if size == 1 else values,
                            "registers": list(values),
                            "detected_type": detected_type,
                            "address": addr,
                            "size": size,
                        }
                
                # DECODED MODE: Process through _decode_value
                if detected_type in ("coil", "discrete") and len(values) == 1:
                    decoded_value = bool(values[0])
                else:
                    decoded_value = values

                return self._decode_value(decoded_value, entity_config)
                
            except Exception as err:
                _LOGGER.error("Read failed at %s: %s", address, err)
                return None
    
    async def async_write_entity(
        self,
        address: str,
        value: Any,
        entity_config: dict,
        **kwargs
    ) -> bool:
        """Write a single Modbus entity (for services/number entities)."""
        if not await self._async_connect():
            return False

        try:
            reg_type = entity_config.get("register_type", "holding").lower()
            # this could potentially override type. So if the user makes a mistake...
            size = kwargs.get("size") or TYPE_SIZES.get(entity_config.get("data_type", "uint16").lower(), 1)
            # Special case for coils — expect single bool
            if reg_type in ("coil"):
                 return await self.client.raw_client.write_coil(
                    address=int(address),
                    value=bool(value),
                    device_id=int(self.client.slave_id),
                )
            elif reg_type in ("discrete"):
                # this is readonly by design?
                _LOGGER.error("Discrete inputs are read-only")
                return False
            else:
                registers = self._encode_value(value, entity_config)
                if registers is None:
                    return False
                write_value = registers

            return await self.client.write(
                address=address,
                value=write_value,
                register_type=reg_type,
            )

        except Exception as err:
            _LOGGER.error("Write failed at %s: %s", address, err)
            return False
