"""SNMP protocol coordinator implementation."""
from __future__ import annotations

import logging
import asyncio
from typing import Any
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from ..base import BaseProtocolCoordinator
from .. import ProtocolRegistry
from .client import SNMPClient
from .const import CONF_ENTITIES, oid_key

_LOGGER = logging.getLogger(__name__)


@ProtocolRegistry.register("snmp")
class SNMPCoordinator(BaseProtocolCoordinator):
    """SNMP protocol coordinator."""
    
    def __init__(
        self,
        hass: HomeAssistant,
        client: SNMPClient,
        config_entry: ConfigEntry,
        update_interval: timedelta,
    ):
        """Initialize SNMP coordinator."""
        super().__init__(
            hass=hass,
            client=client,
            config_entry=config_entry,
            update_interval=update_interval,
            name="SNMP Monitor",
        )
        
        self.protocol_name = "snmp"
        self._lock = asyncio.Lock()
    
    # ----------------------------------------------------------------
    # BaseProtocolCoordinator Implementation
    # ----------------------------------------------------------------
    
    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from configured SNMP entities."""
        if not await self._async_connect():
            _LOGGER.warning("[SNMP] Could not connect to device")
            return {}
        
        entities = self.my_config_entry.options.get(CONF_ENTITIES, [])
        if not entities:
            return {}
        
        new_data = {}
        
        async with self._lock:
            for entity in entities:
                key = oid_key(entity["name"])
                oid = entity["address"]  # In SNMP, "address" is the OID
                
                try:
                    # Read the OID
                    raw_value = await self.client.read(oid)
                    
                    if raw_value is None:
                        _LOGGER.warning("Failed to read OID %s (%s)", oid, entity["name"])
                        continue
                    
                    # Decode the value
                    decoded = self._decode_value(raw_value, entity)
                    
                    if decoded is not None:
                        new_data[key] = decoded
                    else:
                        _LOGGER.warning("Decode returned None for OID %s", entity["name"])
                
                except Exception as err:
                    _LOGGER.error(
                        "Error updating OID '%s': %s",
                        entity.get("name"), err, exc_info=True
                    )
        
        return new_data
    
    def _decode_value(
        self,
        raw_value: Any,
        entity_config: dict,
    ) -> Any | None:
        """
        Decode SNMP value to Python type.
        
        SNMP values come pre-typed from pysnmp, so we convert them to
        appropriate Python types and apply scale/offset if needed.
        """
        if raw_value is None:
            return None
        
        try:
            # Convert pysnmp types to Python types
            from pysnmp.proto.rfc1902 import (
                Integer, Integer32, Gauge32, Counter32, Counter64,
                TimeTicks, IpAddress, OctetString, ObjectIdentifier
            )
            
            # Handle different SNMP types based on what pysnmp returned
            if isinstance(raw_value, (Integer, Integer32, Gauge32)):
                decoded = int(raw_value)
            elif isinstance(raw_value, (Counter32, Counter64)):
                decoded = int(raw_value)
            elif isinstance(raw_value, TimeTicks):
                decoded = int(raw_value)
            elif isinstance(raw_value, IpAddress):
                decoded = str(raw_value)
            elif isinstance(raw_value, OctetString):
                # Try to decode as UTF-8 string, fallback to hex
                try:
                    decoded = raw_value.prettyPrint()
                except Exception:
                    decoded = raw_value.hexValue()
            elif isinstance(raw_value, ObjectIdentifier):
                decoded = raw_value.prettyPrint()
            else:
                # Fallback: convert to string
                decoded = str(raw_value)
            
            # Apply scale and offset if numeric
            if isinstance(decoded, (int, float)):
                scale = entity_config.get("scale", 1.0)
                offset = entity_config.get("offset", 0.0)
                decoded = decoded * scale + offset
            
            return decoded
            
        except Exception as err:
            _LOGGER.error(
                "Error decoding OID '%s' at address %s: %s",
                entity_config.get("name"), entity_config.get("address"), err
            )
            return None
    
    def _encode_value(
        self,
        value: Any,
        entity_config: dict,
    ) -> Any:
        """
        Encode Python value for SNMP SET.
        
        Apply reverse scale/offset, then convert to appropriate SNMP type.
        """
        try:
            data_type = entity_config.get("data_type", "string").lower()
            
            # Reverse scale/offset for numeric types
            if data_type in ("integer", "counter32", "counter64", "gauge32"):
                scale = entity_config.get("scale", 1.0)
                offset = entity_config.get("offset", 0.0)
                if scale != 0 and isinstance(value, (int, float)):
                    value = (value - offset) / scale
                
                # Convert to int
                if isinstance(value, float):
                    value = int(round(value))
            
            # For SNMP, pysnmp will handle type conversion
            # We just return the Python value
            return value
            
        except Exception as err:
            _LOGGER.error(
                "Error encoding value for OID '%s': %s",
                entity_config.get("name"), err
            )
            return None
    
    async def async_read_entity(
        self,
        address: str,
        entity_config: dict,
        **kwargs
    ) -> Any | None:
        """Read a single SNMP OID (for services)."""
        if not await self._async_connect():
            return None
        
        raw = kwargs.get("raw", False)
        
        async with self._lock:
            try:
                raw_value = await self.client.read(address)
                
                if raw_value is None:
                    return None
                
                if raw:
                    # Return raw SNMP response info
                    return {
                        "value": str(raw_value),
                        "type": type(raw_value).__name__,
                        "oid": address,
                    }
                
                return self._decode_value(raw_value, entity_config)
                
            except Exception as err:
                _LOGGER.error("Read failed for OID %s: %s", address, err)
                return None
    
    async def async_write_entity(
        self,
        address: str,
        value: Any,
        entity_config: dict,
        **kwargs
    ) -> bool:
        """Write a single SNMP OID (for services/number entities)."""
        if not await self._async_connect():
            return False
        
        try:
            encoded_value = self._encode_value(value, entity_config)
            if encoded_value is None:
                return False
            
            return await self.client.write(address, encoded_value)
            
        except Exception as err:
            _LOGGER.error("Write failed for OID %s: %s", address, err)
            return False
