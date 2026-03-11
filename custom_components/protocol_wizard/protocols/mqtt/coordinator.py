# custom_components/protocol_wizard/protocols/mqtt/coordinator.py
"""MQTT protocol coordinator implementation - Event-Driven Architecture."""
from __future__ import annotations

import logging
from typing import Any
from datetime import timedelta
import asyncio
import json

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from ..base import BaseProtocolCoordinator
from .. import ProtocolRegistry
from .client import MQTTClient
from ...const import CONF_ENTITIES, CONF_PROTOCOL_MQTT
from .const import topic_key

_LOGGER = logging.getLogger(__name__)


@ProtocolRegistry.register(CONF_PROTOCOL_MQTT)
class MQTTCoordinator(BaseProtocolCoordinator):
    """MQTT protocol coordinator with event-driven pub/sub."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: MQTTClient,
        config_entry: ConfigEntry,
        update_interval: timedelta,
    ):
        """Initialize MQTT coordinator."""
        super().__init__(
            hass=hass,
            client=client,
            config_entry=config_entry,
            update_interval=update_interval,
            name="MQTT Monitor",
        )
        self.protocol_name = CONF_PROTOCOL_MQTT
        self._lock = asyncio.Lock()

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Fetch latest data from configured MQTT entities.
        
        Event-Driven: Just reads from cache, no waiting!
        Messages arrive continuously in background via _on_message callback.
        """
        if not await self._async_connect():
            _LOGGER.warning("[MQTT] Could not connect to broker")
            return {}
        
        if not self.client.is_connected:
            _LOGGER.debug("[MQTT] Client disconnected — skipping entity update")
            return {}
        
        entities = self.my_config_entry.options.get(CONF_ENTITIES, [])
        if not entities:
            return {}

        # Ensure all entity topics are subscribed (persistent, event-driven)
        await self._ensure_subscriptions(entities)

        new_data = {}

        # Just read from cache - instant, no waiting!
        for entity in entities:
            key = topic_key(entity["name"])
            topic = entity["address"]
            
            try:
                # Get cached value (instant!)
                payload = self.client.get_cached_message(topic)
                
                if payload is None:
                    new_data[key] = None
                    continue
                
                # Check if this is a wildcard entity (dict response)
                if isinstance(payload, dict):
                    # Wildcard entity - store count as state, full data as attribute
                    new_data[key] = len(payload)  # State = count of topics
                    new_data[f"{key}_topics"] = list(payload.keys())  # Attribute = topic list
                    new_data[f"{key}_raw"] = payload  # Attribute = full data
                    _LOGGER.debug("Wildcard entity %s has %d topics", key, len(payload))
                else:
                    # Single topic - decode normally
                    decoded = self._decode_value(payload, entity)
                    new_data[key] = decoded
                    # Store raw for debugging
                    new_data[f"{key}_raw"] = payload
                
            except Exception as err:
                _LOGGER.warning(
                    "Failed to read MQTT topic %s: %s",
                    topic,
                    err,
                )
                new_data[key] = None

        return new_data
    
    async def _ensure_subscriptions(self, entities: list[dict]) -> None:
        """
        Ensure all entity topics are subscribed (persistent, event-driven).
        Subscriptions persist across coordinator polls.
        """
        topics = [entity["address"] for entity in entities]
        for topic in topics:
            # Subscribe if not already subscribed
            # Client tracks subscriptions and caches messages automatically
            await self.client.subscribe_persistent(topic)
        
    def _expects_numeric(self, entity_config: dict) -> bool:
        return bool(
            entity_config.get("device_class")
            or entity_config.get("state_class")
        )
        
    def _decode_value(self, raw_value: Any, entity_config: dict) -> Any:
        """
        Decode MQTT payload based on entity configuration.

        Args:
            raw_value: Raw payload from MQTT (could be string, dict, list, etc.)
            entity_config: Entity configuration with data_type, format, etc.
        """
        data_type = entity_config.get("data_type", "string")
        expects_numeric = self._expects_numeric(entity_config)
        options = entity_config.get("options")

        # If no raw data received, return None (HA will show as "unavailable")
        if raw_value is None:
            return None

        # Try options mapping with raw value first (before any conversion)
        if options and isinstance(options, dict):
            raw_str = str(raw_value)
            if raw_str in options:
                return options[raw_str]

        try:
            # If already a dict/list (parsed JSON), handle accordingly
            if isinstance(raw_value, (dict, list)):
                if data_type == "json":
                    # For JSON entities, return formatted string (unless numeric is required)
                    if expects_numeric:
                        # Try to extract numeric value from JSON
                        if isinstance(raw_value, dict) and "value" in raw_value:
                            return self._convert_to_type(raw_value["value"], data_type, expects_numeric)
                        elif isinstance(raw_value, list) and len(raw_value) > 0:
                            return self._convert_to_type(raw_value[0], data_type, expects_numeric)
                        else:
                            return None  # Can't extract numeric from complex JSON
                    return json.dumps(raw_value, indent=2)
                elif data_type == "string" and not expects_numeric:
                    return json.dumps(raw_value)
                else:
                    # Try to extract a number if needed
                    if isinstance(raw_value, dict) and "value" in raw_value:
                        value = raw_value["value"]
                    elif isinstance(raw_value, list) and len(raw_value) > 0:
                        value = raw_value[0]
                    else:
                        # Can't extract value from complex structure
                        if expects_numeric:
                            return None
                        return str(raw_value)
                    
                    return self._convert_to_type(value, data_type, expects_numeric)
            
            # String payload
            if isinstance(raw_value, str):
                # Try to parse as JSON if data_type is json
                if data_type == "json":
                    try:
                        parsed = json.loads(raw_value)
                        if expects_numeric:
                            # Extract numeric from parsed JSON
                            if isinstance(parsed, (int, float)):
                                return parsed
                            elif isinstance(parsed, dict) and "value" in parsed:
                                return self._convert_to_type(parsed["value"], data_type, expects_numeric)
                            else:
                                return None
                        return json.dumps(parsed, indent=2)
                    except json.JSONDecodeError:
                        if expects_numeric:
                            return None  # Invalid JSON for numeric entity
                        return raw_value
                
                # Convert to appropriate type
                return self._convert_to_type(raw_value, data_type, expects_numeric)
            
            # Hex string (binary data)
            if isinstance(raw_value, bytes):
                if expects_numeric:
                    return None  # Binary data can't be numeric
                return raw_value.hex()
            
            # If we got here with a numeric value directly (int/float)
            if isinstance(raw_value, (int, float)):
                return raw_value
            
            # Fallback
            if expects_numeric:
                return None
            return raw_value
            
        except Exception as err:
            _LOGGER.warning("Failed to decode value: %s", err)
            # If numeric entity, return None on error (shows as unavailable)
            # Otherwise return None to avoid invalid state
            return None
            
    def _encode_value(self, raw_value: Any, entity_config: dict) -> Any:
        """
        Encode value for writing to MQTT (used by base class for entity writes).
        
        Args:
            raw_value: The value to encode (from entity state)
            entity_config: Entity configuration with data_type, etc.
        
        Returns:
            Encoded value ready for MQTT publish
        """
        data_type = entity_config.get("data_type", "string")
        
        try:
            if data_type == "json":
                # If it's already a dict/list, convert to JSON string
                if isinstance(raw_value, (dict, list)):
                    return json.dumps(raw_value)
                # If it's a string, try to parse it as JSON to validate
                if isinstance(raw_value, str):
                    try:
                        parsed = json.loads(raw_value)
                        return json.dumps(parsed)
                    except json.JSONDecodeError:
                        return raw_value
                return str(raw_value)
            
            elif data_type == "integer":
                return int(float(raw_value))
            
            elif data_type == "float":
                return float(raw_value)
            
            elif data_type == "boolean":
                if isinstance(raw_value, str):
                    return raw_value.lower() in ("true", "1", "on", "yes")
                return bool(raw_value)
            
            else:  # string (default)
                return str(raw_value)
                
        except (ValueError, TypeError) as err:
            _LOGGER.warning("Failed to encode value %s as %s: %s", raw_value, data_type, err)
            return str(raw_value)
            
    def _convert_to_type(self, value: Any, data_type: str, expects_numeric: bool = False) -> Any:
        """Convert value to specified data type."""
        try:
            if data_type == "integer":
                return int(float(value))
            elif data_type == "float":
                return float(value)
            elif data_type == "boolean":
                if isinstance(value, str):
                    return value.lower() in ("true", "1", "on", "yes")
                return bool(value)
            elif data_type == "string":
                if expects_numeric:
                    # Try to convert string to number for numeric entities
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        return None  # Can't convert to number
                return str(value)
            elif data_type == "json":
                if isinstance(value, str):
                    return json.loads(value)
                return value
            else:
                return value
        except (ValueError, TypeError):
            # Conversion failed
            if expects_numeric:
                return None  # Return None for numeric entities
            return value  # Return original for non-numeric

    async def async_read_entity(
        self,
        address: str,
        entity_config: dict,
        **kwargs,
    ) -> Any:
        """
        Read a single MQTT topic (for services/card).
        Uses client.read() which handles cache + subscribe automatically.
        Supports wildcards - returns formatted dict of topics
        
        Args:
            address: MQTT topic (can include wildcards: + or #)
            entity_config: Entity configuration
            wait_time: How long to wait for message
        """
        if not await self._async_connect():
            return None
        
        try:
            wait_time = kwargs.get("wait_time", 5.0)
    #        _LOGGER.debug("[MQTT] Reading topic %s (wait_time=%.1f)", address, wait_time)
            
            #Client handles everything: cache lookup, subscribe, wait
            payload = await self.client.read(address, wait_time=wait_time)
            
            if payload is None:
                _LOGGER.warning("[MQTT] No message received on %s", address)
                return None
            
            # Check if wildcard response (dict of topics)
            if isinstance(payload, dict) and ('+' in address or '#' in address):
                # Format as readable string for display
                lines = []
                for topic, value in sorted(payload.items()):
                    # Truncate long values
                    value_str = str(value)
                    if len(value_str) > 100:
                        value_str = value_str[:97] + "..."
                    lines.append(f"{topic} = {value_str}")
                
                result = "\n".join(lines)
       #         _LOGGER.info("[MQTT] Wildcard %s matched %d topics", address, len(payload))
                return result
            
            # Single topic - decode normally
            return self._decode_value(payload, entity_config)
            
        except Exception as err:
            _LOGGER.error("Failed to read MQTT topic %s: %s", address, err)
            return None

    async def async_write_entity(
        self,
        address: str,
        value: Any,
        entity_config: dict,
        **kwargs,
    ) -> bool:
        """
        Publish to MQTT topic.
        
        Args:
            address: MQTT topic
            value: Value to publish
            entity_config: Entity configuration
            qos: Quality of Service
            retain: Retain flag
        """
        if not await self._async_connect():
            return False
        
        try:
            qos = kwargs.get("qos", 0)
            retain = kwargs.get("retain", False)
            
            # Convert value if needed
            data_type = entity_config.get("data_type", "string")
            
            if data_type == "json" and not isinstance(value, str):
                # Assume it's already a dict/list
                pass
            elif data_type in ("integer", "float", "boolean"):
                # Paho will handle these
                pass
            else:
                # Convert to string
                value = str(value)
            
     #       _LOGGER.debug("[MQTT] Publishing to %s: %s (qos=%d, retain=%s)", address, value, qos, retain)
            
            return await self.client.write(
                address,
                value,
                qos=qos,
                retain=retain,
            )
            
        except Exception as err:
            _LOGGER.error("Failed to write to MQTT topic %s: %s", address, err)
            return False

    async def _async_connect(self) -> bool:
        """Ensure connection to MQTT broker."""
        if self.client.is_connected:
            return True
        
        try:
            return await self.client.connect()
        except Exception as err:
            _LOGGER.error("Failed to connect to MQTT broker: %s", err)
            return False
