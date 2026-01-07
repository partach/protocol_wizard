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
                oid = entity["address"]
                read_mode = entity.get("read_mode", "get")

                try:
                    if read_mode == "walk":
                        walk_results = await self.client.walk(oid)

                        if not walk_results:
                            new_data[key] = "No results"
                        else:
                            # Sort results by OID for clean order
                            walk_results.sort(key=lambda x: x[0])

                            walk_lines = []
                            current_entry = None
                            for oid_str, value in walk_results:
                                parts = oid_str.split('.')
                                if len(parts) < 2:
                                    walk_lines.append(f"{oid_str} = {value.prettyPrint() if hasattr(value, 'prettyPrint') else value}")
                                    continue

                                entry_id = parts[-2]
                                column_id = parts[-1]

                                if entry_id != current_entry:
                                    if current_entry is not None:
                                        walk_lines.append("")  # blank line between entries
                                    walk_lines.append(f"--- Entry {entry_id} ---")
                                    current_entry = entry_id

                                # Standard column names
                                col_names = {
                                    "1": "Index",
                                    "2": "Description",
                                    "3": "Type",
                                    "4": "MTU",
                                    "5": "Speed",
                                    "6": "MAC Address",
                                    "7": "Admin Status",
                                    "8": "Oper Status",
                                    "10": "In Octets",
                                    "16": "Out Octets",
                                    "18": "In Discards",
                                    "19": "In Errors",
                                    "24": "Out Discards",
                                    "25": "Out Errors",
                                }

                                col_name = col_names.get(column_id, f"Column {column_id}")

                                val_str = value.prettyPrint() if hasattr(value, 'prettyPrint') else str(value)

                                # Skip boring repeated index values (common in vendor tables)
                                if val_str == entry_id and column_id not in col_names:
                                    continue

                                walk_lines.append(f"  {col_name}: {val_str}")

                            new_data[key] = f"Attr.({len(walk_lines)} lines)"
                            new_data[f"{key}_raw"] = "\n".join(walk_lines)
                    else:
                        raw_value = await self.client.read(oid)
                        if raw_value is None:
                            continue
                        # Decode / format
                        decoded = self._decode_value(raw_value, entity_config)
                        formatted = self._format_value(decoded, entity_config)
                        new_data[key] = formatted

                except Exception as err:
                    _LOGGER.error("Error processing %s %s: %s", read_mode, oid, err)

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
