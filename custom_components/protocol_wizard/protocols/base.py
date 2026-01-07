#------------------------------------------
#-- protocol base.py protocol wizard
#------------------------------------------
# protocols/base.py

"""Base protocol abstractions for Protocol Wizard."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class BaseProtocolClient(ABC):
    """Abstract base for protocol clients."""
    
    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection. Returns True if successful."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection."""
        pass
    
    @abstractmethod
    async def read(self, address: str, **kwargs) -> Any:
        """Read value from address. Protocol-specific kwargs."""
        pass
    
    @abstractmethod
    async def write(self, address: str, value: Any, **kwargs) -> bool:
        """Write value to address. Returns True if successful."""
        pass
    
    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Connection status."""
        pass

class _SafeFormatDict(dict):
    """Returns placeholder unchanged if key is missing."""
    def __missing__(self, key):
        return "{" + key + "}"
            
class BaseProtocolCoordinator(DataUpdateCoordinator, ABC):
    """Abstract coordinator for any protocol."""
    
    def __init__(
        self,
        hass: HomeAssistant,
        client: BaseProtocolClient,
        config_entry: ConfigEntry,
        update_interval: timedelta,
        name: str = "Protocol Wizard",
    ):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_interval=update_interval,
        )
        
        self.client = client
        self.my_config_entry = config_entry
        self.protocol_name = "unknown"
    
    @abstractmethod
    async def _async_update_data(self) -> dict[str, Any]:
        """
        Protocol-specific polling logic.
        
        Should return a dict where keys are entity identifiers
        and values are the decoded/processed values.
        """
        pass
    
    @abstractmethod
    def _decode_value(self, raw_value: Any, entity_config: dict) -> Any:
        """
        Protocol-specific decoding.
        
        Args:
            raw_value: Raw value from protocol (registers, OID value, etc.)
            entity_config: Entity configuration dict with data_type, etc.
            
        Returns:
            Decoded Python value (int, float, str, bool, etc.)
        """
        pass
    
    @abstractmethod
    def _encode_value(self, value: Any, entity_config: dict) -> Any:
        """
        Protocol-specific encoding for writes.
        
        Args:
            value: Python value to encode
            entity_config: Entity configuration dict with data_type, etc.
            
        Returns:
            Protocol-specific encoded value
        """
        pass

    def _format_value(self, value: Any, entity_config: dict) -> Any:
        format_str = str(entity_config.get("format", "")).strip()
        if not format_str:
            return value
    
        _LOGGER.debug(
            "Formatting value %s with format '%s'", value, format_str
        )
    
        try:
            ctx = _SafeFormatDict(value=value)
    
            # ---------- STRING HELPERS ----------
            if isinstance(value, str):
                ctx["upper"] = value.upper()
                ctx["lower"] = value.lower()
    
            # ---------- NUMERIC HELPERS ----------
            if isinstance(value, (int, float)):
                total = int(value)
                remaining = total
    
                wants_d = "{d}" in format_str
                wants_h = "{h}" in format_str
                wants_m = "{m}" in format_str
                wants_s = "{s}" in format_str
    
                if wants_d:
                    ctx["d"] = remaining // 86400
                    remaining %= 86400
    
                if wants_h:
                    ctx["h"] = (
                        remaining // 3600
                        if wants_d or wants_m or wants_s
                        else total // 3600
                    )
                    remaining %= 3600
    
                if wants_m:
                    ctx["m"] = (
                        remaining // 60
                        if wants_h or wants_s
                        else total // 60
                    )
                    remaining %= 60
    
                if wants_s:
                    ctx["s"] = remaining
    
            return format_str.format_map(ctx)
    
        except Exception as err:
            _LOGGER.debug(
                "Format error for entity '%s': %s",
                entity_config.get("name"),
                err,
            )
            return value

    
    @abstractmethod
    async def async_read_entity(
        self,
        address: str,
        entity_config: dict,
        **kwargs
    ) -> Any | None:
        """
        Read a single entity value (used by services).
        
        Args:
            address: Protocol-specific address
            entity_config: Entity configuration
            **kwargs: Protocol-specific options
            
        Returns:
            Decoded value or None if failed
        """
        pass
    
    @abstractmethod
    async def async_write_entity(
        self,
        address: str,
        value: Any,
        entity_config: dict,
        **kwargs
    ) -> bool:
        """
        Write a single entity value (used by services/number entities).
        
        Args:
            address: Protocol-specific address
            value: Value to write
            entity_config: Entity configuration
            **kwargs: Protocol-specific options
            
        Returns:
            True if successful
        """
        pass
    
    async def _async_connect(self) -> bool:
        """
        Ensure client is connected.
        Default implementation - protocols can override if needed.
        """
        if self.client.is_connected:
            return True
        
        try:
            return await self.client.connect()
        except Exception as err:
            _LOGGER.error("[%s] Failed to connect: %s", self.protocol_name, err)
            return False
