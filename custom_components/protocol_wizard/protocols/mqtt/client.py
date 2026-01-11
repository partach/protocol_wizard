# custom_components/protocol_wizard/protocols/mqtt/client.py
"""MQTT protocol client implementation."""
from __future__ import annotations

import asyncio
import logging
import json
from typing import Any
from collections import defaultdict

import paho.mqtt.client as mqtt_client

from ..base import BaseProtocolClient

_LOGGER = logging.getLogger(__name__)


class MQTTClient(BaseProtocolClient):
    """MQTT client wrapper for Protocol Wizard."""

    def __init__(
        self,
        broker: str,
        port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        client_id: str | None = None,
        timeout: float = 10.0,
    ):
        """Initialize MQTT client."""
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout

        self._client: mqtt_client.Client | None = None
        self._connected = False
        self._subscriptions: dict[str, Any] = {}  # topic -> last_message
        self._subscribe_futures: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        
        # Generate client ID
        if client_id:
            self._client_id = client_id
        else:
            import random
            self._client_id = f"protocol_wizard_{random.randint(1000, 9999)}"

    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker."""
        if rc == 0:
            _LOGGER.debug("MQTT connected to %s:%s", self.broker, self.port)
            self._connected = True
        else:
            _LOGGER.error("MQTT connection failed with code %s", rc)
            self._connected = False

    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from broker."""
        _LOGGER.debug("MQTT disconnected from %s:%s (rc=%s)", self.broker, self.port, rc)
        self._connected = False

    def _on_message(self, client, userdata, msg):
        """Callback when message received."""
        topic = msg.topic
        
        try:
            # Try to decode as JSON
            payload = msg.payload.decode('utf-8')
            try:
                payload_data = json.loads(payload)
            except json.JSONDecodeError:
                # Not JSON, keep as string
                payload_data = payload
        except UnicodeDecodeError:
            # Binary data
            payload_data = msg.payload.hex()
        
        # Store message
        self._subscriptions[topic] = {
            "payload": payload_data,
            "qos": msg.qos,
            "retain": msg.retain,
            "timestamp": asyncio.get_event_loop().time(),
        }
        
        # Resolve any waiting futures
        if topic in self._subscribe_futures:
            future = self._subscribe_futures.pop(topic)
            if not future.done():
                future.set_result(payload_data)

    async def connect(self) -> bool:
        """Establish connection to MQTT broker."""
        try:
            if self._client is None:
                self._client = mqtt_client.Client(self._client_id)
                
                if self.username and self.password:
                    self._client.username_pw_set(self.username, self.password)
                
                self._client.on_connect = self._on_connect
                self._client.on_disconnect = self._on_disconnect
                self._client.on_message = self._on_message

            # Connect in thread-safe way
            def do_connect():
                self._client.connect(self.broker, self.port, keepalive=60)
                self._client.loop_start()
            
            await asyncio.get_event_loop().run_in_executor(None, do_connect)
            
            # Wait for connection
            for _ in range(int(self.timeout * 10)):
                if self._connected:
                    return True
                await asyncio.sleep(0.1)
            
            _LOGGER.error("MQTT connection timeout to %s:%s", self.broker, self.port)
            return False
            
        except Exception as err:
            _LOGGER.error("MQTT connection failed: %s", err)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        if self._client:
            try:
                def do_disconnect():
                    self._client.loop_stop()
                    self._client.disconnect()
                
                await asyncio.get_event_loop().run_in_executor(None, do_disconnect)
            except Exception as err:
                _LOGGER.debug("Error disconnecting MQTT client: %s", err)
            finally:
                self._client = None
                self._connected = False
                self._subscriptions.clear()

    async def read(self, address: str, **kwargs) -> Any:
        """
        Subscribe to MQTT topic and wait for message.
        
        Args:
            address: MQTT topic to subscribe to
            wait_time: How long to wait for message (default: 5 seconds)
        
        Returns:
            Last received message payload or waits for new message
        """
        if not self._connected:
            raise ConnectionError("MQTT client not connected")
        
        topic = address
        wait_time = kwargs.get("wait_time", 5.0)
        
        # Check if we already have a cached message
        if topic in self._subscriptions:
            cached = self._subscriptions[topic]
            # Return cached if recent (within 60 seconds)
            if asyncio.get_event_loop().time() - cached["timestamp"] < 60:
                return cached["payload"]
        
        # Subscribe and wait for new message
        async with self._lock:
            future = asyncio.Future()
            self._subscribe_futures[topic] = future
            
            def do_subscribe():
                self._client.subscribe(topic)
            
            await asyncio.get_event_loop().run_in_executor(None, do_subscribe)
        
        try:
            # Wait for message
            payload = await asyncio.wait_for(future, timeout=wait_time)
            return payload
        except asyncio.TimeoutError:
            # Return cached message if available
            if topic in self._subscriptions:
                return self._subscriptions[topic]["payload"]
            return None
        finally:
            # Clean up future
            self._subscribe_futures.pop(topic, None)

    async def write(self, address: str, value: Any, **kwargs) -> bool:
        """
        Publish message to MQTT topic.
        
        Args:
            address: MQTT topic to publish to
            value: Message payload (will be JSON-encoded if dict/list)
            qos: Quality of Service (0, 1, or 2)
            retain: Whether to retain message
        
        Returns:
            True if successful
        """
        if not self._connected:
            raise ConnectionError("MQTT client not connected")
        
        topic = address
        qos = kwargs.get("qos", 0)
        retain = kwargs.get("retain", False)
        
        # Convert value to string/bytes
        if isinstance(value, (dict, list)):
            payload = json.dumps(value)
        elif isinstance(value, bytes):
            payload = value
        else:
            payload = str(value)
        
        try:
            def do_publish():
                result = self._client.publish(topic, payload, qos=qos, retain=retain)
                return result.rc == mqtt_client.MQTT_ERR_SUCCESS
            
            success = await asyncio.get_event_loop().run_in_executor(None, do_publish)
            
            if success:
                _LOGGER.debug("Published to %s: %s", topic, payload)
            else:
                _LOGGER.error("Failed to publish to %s", topic)
            
            return success
            
        except Exception as err:
            _LOGGER.error("MQTT publish error: %s", err)
            return False

    async def subscribe_multiple(self, topics: list[str]) -> dict[str, Any]:
        """
        Subscribe to multiple topics and return current values.
        
        Args:
            topics: List of MQTT topics
        
        Returns:
            Dict of topic -> payload
        """
        if not self._connected:
            raise ConnectionError("MQTT client not connected")
        
        def do_subscribe():
            for topic in topics:
                self._client.subscribe(topic)
        
        await asyncio.get_event_loop().run_in_executor(None, do_subscribe)
        
        # Wait a bit for messages
        await asyncio.sleep(0.5)
        
        # Return current subscriptions
        return {
            topic: self._subscriptions.get(topic, {}).get("payload")
            for topic in topics
        }

    @property
    def is_connected(self) -> bool:
        """Return connection status."""
        return self._connected and self._client is not None

    def get_subscribed_topics(self) -> list[str]:
        """Get list of currently subscribed topics."""
        return list(self._subscriptions.keys())

    def get_topic_data(self, topic: str) -> dict[str, Any] | None:
        """Get full data for a topic including QoS and retain flag."""
        return self._subscriptions.get(topic)
