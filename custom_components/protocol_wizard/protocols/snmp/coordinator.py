# custom_components/protocol_wizard/protocols/snmp/coordinator.py
"""SNMP protocol coordinator implementation."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .. import ProtocolRegistry
from ..base import BaseProtocolCoordinator
from .client import SNMPClient
from .const import CONF_ENTITIES, oid_key

_LOGGER = logging.getLogger(__name__)
# Reduce noise from HA
# Setting parent logger to CRITICAL to catch all sub-loggers
logging.getLogger("homeassistant.helpers.update_coordinator").setLevel(logging.CRITICAL)

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
        if not self.client.is_connected: # protect prolongued query of snmp if not needed
            _LOGGER.debug("[Modbus] Hub reports disconnected — skipping entity update")
            return {}
        entities = self.my_config_entry.options.get(CONF_ENTITIES, [])
        if not entities:
            return {}

        new_data = {}
        failed_count = 0
        consecutive_failures = 0
        max_consecutive_failures = 2
        # Also limit total failures to prevent long update cycles
        max_total_failures = min(5, max(2, len(entities) // 3))

        async with self._lock:
            for entity in entities:
                # Early abort if device is clearly dead (consecutive failures)
                if consecutive_failures >= max_consecutive_failures:
                    _LOGGER.warning(
                        "[SNMP] Too many consecutive failures (%d) — aborting update cycle",
                        max_consecutive_failures
                    )
                    break

                # Also abort if too many total failures (even if not consecutive)
                if failed_count >= max_total_failures:
                    _LOGGER.warning(
                        "[SNMP] Too many total failures (%d/%d) — aborting update cycle",
                        failed_count, len(entities)
                    )
                    break

                key = oid_key(entity["name"])
                oid = entity["address"]
                read_mode = entity.get("read_mode", "get")

                try:
                    if read_mode == "walk":
                        walk_results = await self.client.walk(oid)

                        if not walk_results:
                            new_data[key] = "No results"
                            new_data[f"{key}_raw"] = []  # empty list
                            failed_count += 1
                            consecutive_failures += 1
                        else:
                            consecutive_failures = 0  # reset on success
                            # Simple, straight OID = value dump
                            walk_lines = [
                                f"{oid_str} = {value.prettyPrint() if hasattr(value, 'prettyPrint') else value}"
                                for oid_str, value in walk_results
                            ]

                            new_data[key] = f"Attr.({len(walk_lines)} lines)"
                            new_data[f"{key}_raw"] = walk_lines
                    else:
                        raw_value = await self.client.read(oid)
                        if raw_value is None:
                            failed_count += 1
                            consecutive_failures += 1
                            continue
                        consecutive_failures = 0  # reset on success
                        # Decode / format
                        decoded = self._decode_value(raw_value, entity)
                        formatted = self._format_value(decoded, entity)
                        new_data[key] = formatted

                except Exception as err:
                    _LOGGER.error("Error processing %s %s: %s", read_mode, oid, err)
                    failed_count += 1
                    consecutive_failures += 1

        # Log summary if there were failures
        if failed_count > 0:
            _LOGGER.info("[SNMP] Update completed with %d/%d failures", failed_count, len(entities))

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
                    value = round(float(value))

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
                raw_value = await self.client.walk(address)

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
