# custom_components/protocol_wizard/protocols/mqtt/client.py
"""MQTT protocol client implementation - Event-Driven Architecture."""
from __future__ import annotations

import asyncio
import logging
import json
from typing import Any

import paho.mqtt.client as mqtt_client

from ..base import BaseProtocolClient

_LOGGER = logging.getLogger(__name__)


class MQTTClient(BaseProtocolClient):
    """MQTT client with event-driven pub/sub architecture."""

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
        
        # Message cache: topic -> {payload, qos, retain, timestamp}
        self._message_cache: dict[str, dict] = {}
        
        # Track subscribed topics (persistent subscriptions)
        self._subscribed_topics: set[str] = set()
        
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
            _LOGGER.info("MQTT connected to %s:%s", self.broker, self.port)
            self._connected = True
            
            # Resubscribe to all topics on reconnect
            if self._subscribed_topics:
    #            _LOGGER.info("Resubscribing to %d topics", len(self._subscribed_topics))
                for topic in self._subscribed_topics:
                    try:
                        self._client.subscribe(topic, qos=0)
     #                   _LOGGER.debug("Resubscribed to %s", topic)
                    except Exception as err:
                        _LOGGER.error("Failed to resubscribe to %s: %s", topic, err)
        else:
            _LOGGER.error("MQTT connection failed with code %s", rc)
            self._connected = False

    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from broker."""
        _LOGGER.debug("MQTT disconnected from %s:%s (rc=%s)", self.broker, self.port, rc)
        self._connected = False

    def _on_message(self, client, userdata, msg):
        """
        Callback when message received (event-driven!).
        This runs continuously in background, caching ALL messages.
        NOTE: This runs in paho-mqtt's thread, not asyncio!
        """
        import time
        
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
        
        # Cache the message (this is the key!)
        self._message_cache[topic] = {
            "payload": payload_data,
            "qos": msg.qos,
            "retain": msg.retain,
            "timestamp": time.time(),  # Use time.time() not asyncio
        }
        
   #     _LOGGER.debug("Cached message for topic %s: %s", topic, payload_data)

    async def connect(self) -> bool:
        """Establish connection to MQTT broker and start background loop."""
        try:
            if self._client is None:
                # Use CallbackAPIVersion.VERSION1 for compatibility with paho-mqtt 2.x
                self._client = mqtt_client.Client(
                    client_id=self._client_id,
                    callback_api_version=mqtt_client.CallbackAPIVersion.VERSION1
                )
                
                if self.username and self.password:
                    self._client.username_pw_set(self.username, self.password)
                
                self._client.on_connect = self._on_connect
                self._client.on_disconnect = self._on_disconnect
                self._client.on_message = self._on_message

            # Connect in thread-safe way
            def do_connect():
                self._client.connect(self.broker, self.port, keepalive=60)
                self._client.loop_start()  # ✅ Start background message receiver!
            
            await asyncio.get_event_loop().run_in_executor(None, do_connect)
            
            # Wait for connection
            for _ in range(int(self.timeout * 10)):
                if self._connected:
           #         _LOGGER.info("MQTT background loop started successfully")
                    return True
                await asyncio.sleep(0.1)
            
            _LOGGER.error("MQTT connection timeout to %s:%s", self.broker, self.port)
            return False
            
        except Exception as err:
            _LOGGER.error("MQTT connection failed: %s", err)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close connection and stop background loop."""
        if self._client:
            try:
                def do_disconnect():
                    self._client.loop_stop()
                    self._client.disconnect()
                
                await asyncio.get_event_loop().run_in_executor(None, do_disconnect)
                _LOGGER.info("MQTT disconnected and loop stopped")
            except Exception as err:
                _LOGGER.error("Error during MQTT disconnect: %s", err)
            
            self._connected = False

    async def subscribe_persistent(self, topic: str, qos: int = 0) -> bool:
        """
        Subscribe to topic persistently (event-driven).
        Messages are automatically cached by _on_message callback.
        
        Args:
            topic: MQTT topic (can use wildcards: + or #)
            qos: Quality of Service
            
        Returns:
            True if subscribed successfully
        """
        if not self._connected:
            _LOGGER.warning("Cannot subscribe - not connected")
            return False
        
        # Already subscribed?
        if topic in self._subscribed_topics:
      #      _LOGGER.debug("Already subscribed to %s", topic)
            return True
        
        try:
            def do_subscribe():
                result = self._client.subscribe(topic, qos=qos)
                return result[0] == mqtt_client.MQTT_ERR_SUCCESS
            
            success = await asyncio.get_event_loop().run_in_executor(None, do_subscribe)
            
            if success:
                self._subscribed_topics.add(topic)
        #        _LOGGER.info("Subscribed to %s (persistent)", topic)
                return True
            else:
                _LOGGER.error("Failed to subscribe to %s", topic)
                return False
                
        except Exception as err:
            _LOGGER.error("MQTT subscribe error: %s", err)
            return False

    def get_cached_message(self, topic: str) -> Any | None:
        """
        Get cached message for topic (instant!).
        Supports wildcards: + (single level) and # (multi-level)
        
        Args:
            topic: MQTT topic (can include wildcards)
            
        Returns:
            Cached payload or None if no message received yet
            If wildcard used, returns dict of {topic: payload}
        """
        # Check if topic contains wildcards
        if '+' in topic or '#' in topic:
            import re
            # First, escape all regex special characters EXCEPT + and #
            # Then convert MQTT wildcards to regex patterns
            pattern = re.escape(topic)  # Escape everything first
            pattern = pattern.replace(r'\+', '[^/]+')  # + = single level (no slashes)
            pattern = pattern.replace(r'\#', '.*')     # # = multi-level (anything)
            pattern = f"^{pattern}$"
            
     #       _LOGGER.debug("Wildcard pattern: %s → regex: %s", topic, pattern)
            
            regex = re.compile(pattern)
            
            # Find all matching topics
            matches = {}
            for cached_topic, cached_data in self._message_cache.items():
                if regex.match(cached_topic):
                    matches[cached_topic] = cached_data["payload"]
            
    #        _LOGGER.debug("Wildcard %s matched %d topics", topic, len(matches))
            return matches if matches else None
        else:
            # Exact topic match
            cached = self._message_cache.get(topic)
            if cached:
                return cached["payload"]
            return None

    async def read(self, address: str, **kwargs) -> Any | None:
        """
        Read from MQTT topic (for card/services).
        For one-time reads, subscribe temporarily and wait for message.
        Supports wildcards: + (single level) and # (multi-level)
        
        Args:
            address: MQTT topic (can include wildcards)
            wait_time: How long to wait for message
            
        Returns:
            Payload, dict of {topic: payload} for wildcards, or None
        """
        topic = address
        wait_time = kwargs.get("wait_time", 5.0)
        is_wildcard = '+' in topic or '#' in topic
        
        # Check if already cached (from persistent subscription)
        cached = self.get_cached_message(topic)
        if cached is not None:
            if is_wildcard:
     #           _LOGGER.debug("Returning %d cached topics matching %s", len(cached), topic)
              pass
            else:
      #          _LOGGER.debug("Returning cached value for %s", topic)
              pass
            return cached
        
        # Not cached - subscribe and wait for message
        if is_wildcard:
#            _LOGGER.debug("Subscribing to wildcard %s and waiting %.1fs", topic, wait_time)
            pass
        else:
 #           _LOGGER.debug("No cache for %s, subscribing and waiting %.1fs", topic, wait_time)
            pass
        # Subscribe (will start caching messages)
        success = await self.subscribe_persistent(topic)
        if not success:
            _LOGGER.error("Failed to subscribe to %s", topic)
            return None
        
        # IMPORTANT: Give broker time to send retained messages!
        # Wildcards may match MANY topics (e.g., $SYS/# = 100+ topics)
        # so we need to wait longer for all retained messages to arrive
        if is_wildcard:
            # Poll cache while waiting - messages arrive over ~1-2 seconds
            poll_deadline = asyncio.get_event_loop().time() + 2.0
            last_count = 0
            stable_checks = 0
            
            while asyncio.get_event_loop().time() < poll_deadline:
                await asyncio.sleep(0.2)  # Check every 200ms
                cached = self.get_cached_message(topic)
                
                if cached:
                    current_count = len(cached)
                    if current_count > last_count:
                        # Still receiving messages
         #               _LOGGER.debug("Wildcard %s: %d topics received", topic, current_count)
                        last_count = current_count
                        stable_checks = 0
                    else:
                        # Count stable - might be done
                        stable_checks += 1
                        if stable_checks >= 3:  # Stable for 600ms
          #                  _LOGGER.debug("Wildcard %s: stabilized at %d topics", topic, current_count)
                            break
            
      #      _LOGGER.info("Wildcard %s: received %d total topics", topic, last_count)
        else:
            await asyncio.sleep(0.5)  # 500ms for single topics
        
        # Check cache immediately after subscribe (retained messages should be here)
        cached = self.get_cached_message(topic)
        if cached is not None:
            if is_wildcard:
       #         _LOGGER.info("Got %d retained topics matching %s after subscribe", len(cached), topic)
                pass
            else:
       #         _LOGGER.info("Got retained message for %s immediately after subscribe", topic)
                pass
            return cached
        
        # No retained message - wait for live message
        if is_wildcard:
   #         _LOGGER.debug("No retained messages for %s, waiting for live messages", topic)
            pass
        else:
    #        _LOGGER.debug("No retained message for %s, waiting for live message", topic)
            pass
        deadline = asyncio.get_event_loop().time() + wait_time
        while asyncio.get_event_loop().time() < deadline:
            cached = self.get_cached_message(topic)
            if cached is not None:
                if is_wildcard:
   #                 _LOGGER.info("Got %d live topics matching %s", len(cached), topic)
                    pass
                else:
    #                _LOGGER.info("Got live message for %s", topic)
                    pass
                return cached
            await asyncio.sleep(0.1)
        
        _LOGGER.warning("No message received matching %s after %.1fs", topic, wait_time)
        return None

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
                # For QoS > 0, wait for publish to complete (with timeout)
                if qos > 0:
                    result.wait_for_publish(timeout=5.0)
                return result.rc == mqtt_client.MQTT_ERR_SUCCESS
            
            # Run in executor with timeout wrapper
            try:
                success = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, do_publish),
                    timeout=10.0  # 10 second timeout for publish
                )
            except asyncio.TimeoutError:
                _LOGGER.error("MQTT publish timeout for topic %s", topic)
                return False
            
            if success:
       #         _LOGGER.debug("Published to %s: %s (qos=%d, retain=%s)", topic, payload, qos, retain)
                pass
            else:
                _LOGGER.error("Failed to publish to %s", topic)
            
            return success
            
        except Exception as err:
            _LOGGER.error("MQTT publish error: %s", err)
            return False

    @property
    def is_connected(self) -> bool:
        """Connection status."""
        return self._connected
    
    def get_subscription_count(self) -> int:
        """Get number of active subscriptions."""
        return len(self._subscribed_topics)
    
    def get_cache_size(self) -> int:
        """Get number of cached messages."""
        return len(self._message_cache)
