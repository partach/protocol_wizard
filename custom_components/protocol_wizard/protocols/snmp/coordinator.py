# custom_components/protocol_wizard/protocols/snmp/coordinator.py
"""SNMP protocol coordinator implementation."""
from __future__ import annotations

import logging
from typing import Any
from datetime import timedelta
import asyncio
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
                oid = entity["address"]  # In SNMP, "address" is the OID string

                try:
                    raw_value = await self.client.read(oid)

                    if raw_value is None:
                        _LOGGER.debug("No response for OID %s (%s)", oid, entity["name"])
                        continue

                    decoded = self._decode_value(raw_value, entity)
                    if decoded is not None:
                        new_data[key] = decoded

                except Exception as err:
                    _LOGGER.error(
                        "Error reading OID %s (%s): %s",
                        oid,
                        entity.get("name"),
                        err,
                    )

        return new_data

    def _decode_value(self, raw_value: Any, entity_config: dict) -> Any | None:
        """Decode SNMP value to Python type with scale/offset support."""
        if raw_value is None:
            return None

        try:
            # pysnmp returns typed objects — convert to basic Python types
            if hasattr(raw_value, "prettyPrint"):
                decoded = raw_value.prettyPrint()
            else:
                decoded = str(raw_value)

            # Attempt numeric conversion based on data_type
            data_type = entity_config.get("data_type", "string").lower()

            if data_type in ("integer", "counter32", "counter64", "gauge32", "timeticks"):
                try:
                    decoded = int(decoded)
                except (ValueError, TypeError):
                    _LOGGER.warning("Failed to convert %s to int for %s", decoded, entity_config["name"])
                    return None
            elif data_type == "float":
                try:
                    decoded = float(decoded)
                except (ValueError, TypeError):
                    return None

            # Apply scale and offset (only for numeric values)
            if isinstance(decoded, (int, float)):
                scale = entity_config.get("scale", 1.0)
                offset = entity_config.get("offset", 0.0)
                decoded = decoded * scale + offset

            return decoded

        except Exception as err:
            _LOGGER.error("Decode error for OID %s: %s", entity_config.get("address"), err)
            return None

    def _encode_value(self, value: Any, entity_config: dict) -> Any:
        """Encode Python value for SNMP SET (reverse scale/offset)."""
        try:
            data_type = entity_config.get("data_type", "string").lower()

            # Reverse scale/offset for numeric types
            if data_type in ("integer", "counter32", "counter64", "gauge32", "float"):
                scale = entity_config.get("scale", 1.0)
                offset = entity_config.get("offset", 0.0)
                if scale != 0:
                    value = (value - offset) / scale

                if data_type != "float":
                    value = int(round(float(value)))

            # pysnmp handles type mapping — just return clean Python value
            return value

        except Exception as err:
            _LOGGER.error("Encode error for %s: %s", entity_config.get("name"), err)
            return None

    async def async_read_entity(
        self,
        address: str,
        entity_config: dict,
        **kwargs,
    ) -> Any | None:
        """Read a single SNMP OID (used by services)."""
        if not await self._async_connect():
            return None

        raw = kwargs.get("raw", False)

        async with self._lock:
            try:
                raw_value = await self.client.read(address)

                if raw_value is None:
                    return None

                if raw:
                    return {
                        "value": str(raw_value),
                        "type": type(raw_value).__name__,
                        "oid": address,
                    }

                return self._decode_value(raw_value, entity_config)

            except Exception as err:
                _LOGGER.error("Service read failed for OID %s: %s", address, err)
                return None

    async def async_write_entity(
        self,
        address: str,
        value: Any,
        entity_config: dict,
        **kwargs,
    ) -> bool:
        """Write to a single SNMP OID."""
        if not await self._async_connect():
            return False

        try:
            encoded = self._encode_value(value, entity_config)
            if encoded is None:
                return False

            success = await self.client.write(address, encoded)

            if success:
                # Immediate refresh so UI updates instantly
                await self.async_request_refresh()

            return success

        except Exception as err:
            _LOGGER.error("Write failed for OID %s: %s", address, err)
            return False
