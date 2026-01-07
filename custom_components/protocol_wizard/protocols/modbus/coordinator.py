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
        """Fetch latest data from configured Modbus entities."""
        if not await self._async_connect():
            _LOGGER.warning("[Modbus] Could not connect to device")
            return {}
        
        entities = self.my_config_entry.options.get(CONF_ENTITIES, [])
        if not entities:
            return {}
        
        updated_entities = [dict(reg) for reg in entities]
        options_changed = False
        new_data = {}
        
        async with self._lock:
            for idx, reg in enumerate(updated_entities):
                key = reg_key(reg["name"])
                address = int(reg["address"])
                count = int(TYPE_SIZES.get(reg["data_type"].lower(), 1))
                reg_type = reg.get("register_type", "holding")
                
                result = None
                try:
                    # Auto-detect register type
                    if reg_type == "auto":
                        methods = [
                            ("holding", self.client.raw_client.read_holding_registers),
                            ("input", self.client.raw_client.read_input_registers),
                        ]
                        if reg.get("allow_bits", False):
                            methods += [
                                ("coil", self.client.raw_client.read_coils),
                                ("discrete", self.client.raw_client.read_discrete_inputs),
                            ]
                        
                        for name, method in methods:
                            try:
                                result = await method(
                                    address=address,
                                    count=count,
                                    device_id=self.client.slave_id,
                                )
                                if not result.isError():
                                    if name in ("holding", "input") and hasattr(result, "registers"):
                                        reg_type = name
                                        updated_entities[idx]["register_type"] = name
                                        options_changed = True
                                        break
                                    if name in ("coil", "discrete") and hasattr(result, "bits"):
                                        reg_type = name
                                        updated_entities[idx]["register_type"] = name
                                        options_changed = True
                                        break
                            except Exception:
                                continue
                        
                        if reg_type == "auto":
                            _LOGGER.warning(
                                "Auto-detect failed for register '%s' at address %s",
                                reg["name"], address
                            )
                            continue
                    
                    # Direct read if not auto or auto succeeded
                    if result is None:
                        raw_client = self.client.raw_client
                        if reg_type == "holding":
                            result = await raw_client.read_holding_registers(
                                address=address, count=count, device_id=self.client.slave_id
                            )
                        elif reg_type == "input":
                            result = await raw_client.read_input_registers(
                                address=address, count=count, device_id=self.client.slave_id
                            )
                        elif reg_type == "coil":
                            result = await raw_client.read_coils(
                                address=address, count=count, device_id=self.client.slave_id
                            )
                        elif reg_type == "discrete":
                            result = await raw_client.read_discrete_inputs(
                                address=address, count=count, device_id=self.client.slave_id
                            )
                        else:
                            _LOGGER.error("Unknown register_type '%s' for '%s'", reg_type, reg["name"])
                            continue
                    
                    if result.isError():
                        _LOGGER.warning(
                            "Read failed for '%s' (type=%s, addr=%s): %s",
                            reg["name"], reg_type, address, result
                        )
                        continue
                    
                    # Extract values
                    if reg_type in ("coil", "discrete"):
                        values = result.bits[:count]
                    else:
                        values = result.registers[:count]
                    
                    if not values:
                        _LOGGER.warning("No values returned for register '%s'", reg["name"])
                        continue
                    
                    # Decode / format
                    decoded = self._decode_value(values, reg)
                    formatted = self._format_value(decoded, reg)
                    new_data[key] = formatted
                
                except Exception as err:
                    _LOGGER.error(
                        "Error updating register '%s': %s",
                        reg.get("name"), err, exc_info=True
                    )
        
        if options_changed:
            _LOGGER.info("Detected register types updated")
        
        return new_data
    
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
                # Handle auto-detect if needed
                detected_type = reg_type
                result = None
                
                if reg_type == "auto":
                    methods = [
                        ("holding", self.client.raw_client.read_holding_registers),
                        ("input", self.client.raw_client.read_input_registers),
                        ("coil", self.client.raw_client.read_coils),
                        ("discrete", self.client.raw_client.read_discrete_inputs),
                    ]
                    
                    for name, method in methods:
                        try:
                            result = await method(
                                address=int(addr),
                                count=int(size),
                                device_id=int(self.client.slave_id),
                            )
                            if not result.isError():
                                if name in ("holding", "input") and hasattr(result, "registers"):
                                    detected_type = name
                                    break
                                if name in ("coil", "discrete") and hasattr(result, "bits"):
                                    detected_type = name
                                    break
                        except Exception:
                            continue
                    
                    if result is None or result.isError():
                        _LOGGER.warning("Auto-detect failed at address %s", addr)
                        return None
                    
                    # Extract values from result
                    if detected_type in ("coil", "discrete"):
                        values = result.bits[:size]
                    else:
                        values = result.registers[:size]
                else:
                    method_map = {
                        "holding": self.client.read_holding_registers,
                        "input": self.client.read_input_registers,
                        "coil": self.client.read_coils,
                        "discrete": self.client.read_discrete_inputs,
                    }
                    method = method_map.get(reg_type)
                    if method is None:
                        _LOGGER.error("Invalid register_type: %s", reg_type)
                        return None
        
                    try:
                        result = await method(
                            address=int(addr),
                            count=int(size),
                            device_id=int(self.slave_id),
                        )
                    except Exception as err:
                        _LOGGER.error("Read failed for %s register at %d: %s", reg_type, addr, err)
                        return None
                
                if values is None:
                    return None
                if raw and detected_type in ("coil", "discrete") and size == 1:
                    return {
                        "value": bool(values[0]),
                        "detected_type": detected_type,
                        "address": addr,
                    }
                # Return raw mode with full info
                if raw:
                    return {
                        "registers": values if not isinstance(values[0], bool) else [],
                        "bits": values if isinstance(values[0], bool) else [],
                        "detected_type": detected_type,
                        "address": addr,
                        "size": size,
                    }
                if detected_type in ("coil", "discrete") and len(values) == 1:
                    decoded_value = bool(values[0])
                else:
                    decoded_value = values

                return self._decode_value(decoded_value, entity_config)
                # Return decoded value
                return self._decode_value(values, entity_config)
                
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

            # Special case for coils — expect single bool
            if reg_type in ("coil", "discrete"):
                # Convert to 0/1 int for pymodbus
                write_value = [1 if bool(value) else 0]
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
