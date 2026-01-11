# custom_components/protocol_wizard/protocols/mqtt/coordinator.py
"""MQTT protocol coordinator implementation."""
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
from .const import CONF_ENTITIES, topic_key

_LOGGER = logging.getLogger(__name__)


@ProtocolRegistry.register("mqtt")
class MQTTCoordinator(BaseProtocolCoordinator):
    """MQTT protocol coordinator."""

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
        self.protocol_name = "mqtt"
        self._lock = asyncio.Lock()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from configured MQTT entities."""
        if not await self._async_connect():
            _LOGGER.warning("[MQTT] Could not connect to broker")
            return {}
        
        if not self.client.is_connected:
            _LOGGER.debug("[MQTT] Client disconnected — skipping entity update")
            return {}
        
        entities = self.my_config_entry.options.get(CONF_ENTITIES, [])
        if not entities:
            return {}

        new_data = {}

        async with self._lock:
            # Get all topics to subscribe
            topics = [entity["address"] for entity in entities]
            
            # Subscribe to all topics and get current values
            topic_values = await self.client.subscribe_multiple(topics)
            
            for entity in entities:
                key = topic_key(entity["name"])
                topic = entity["address"]
                
                try:
                    payload = topic_values.get(topic)
                    
                    if payload is None:
                        new_data[key] = "No data"
                        continue
                    
                    # Decode the value
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
                    new_data[key] = "Error"

        return new_data

    def _decode_value(self, raw_value: Any, entity_config: dict) -> Any:
        """
        Decode MQTT payload based on entity configuration.
        
        Args:
            raw_value: Raw payload from MQTT (could be string, dict, list, etc.)
            entity_config: Entity configuration with data_type, format, etc.
        """
        data_type = entity_config.get("data_type", "string")
        
        try:
            # If already a dict/list (parsed JSON), handle accordingly
            if isinstance(raw_value, (dict, list)):
                if data_type == "json":
                    # Return as-is or formatted string
                    return json.dumps(raw_value, indent=2)
                elif data_type == "string":
                    return json.dumps(raw_value)
                else:
                    # Try to extract a number if needed
                    if isinstance(raw_value, dict) and "value" in raw_value:
                        value = raw_value["value"]
                    elif isinstance(raw_value, list) and len(raw_value) > 0:
                        value = raw_value[0]
                    else:
                        return str(raw_value)
                    
                    return self._convert_to_type(value, data_type)
            
            # String payload
            if isinstance(raw_value, str):
                # Try to parse as JSON if data_type is json
                if data_type == "json":
                    try:
                        parsed = json.loads(raw_value)
                        return json.dumps(parsed, indent=2)
                    except json.JSONDecodeError:
                        return raw_value
                
                # Convert to appropriate type
                return self._convert_to_type(raw_value, data_type)
            
            # Hex string (binary data)
            if isinstance(raw_value, bytes):
                return raw_value.hex()
            
            return raw_value
            
        except Exception as err:
            _LOGGER.warning("Failed to decode value: %s", err)
            return str(raw_value)

    def _convert_to_type(self, value: Any, data_type: str) -> Any:
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
                return str(value)
            elif data_type == "json":
                if isinstance(value, str):
                    return json.loads(value)
                return value
            else:
                return value
        except (ValueError, TypeError):
            return value

    async def async_read_entity(
        self,
        address: str,
        entity_config: dict,
        **kwargs,
    ) -> Any:
        """
        Read a single MQTT topic.
        
        Args:
            address: MQTT topic
            entity_config: Entity configuration
            wait_time: How long to wait for message
        """
        if not await self._async_connect():
            return None
        
        try:
            wait_time = kwargs.get("wait_time", 5.0)
            payload = await self.client.read(address, wait_time=wait_time)
            
            if payload is None:
                return None
            
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
