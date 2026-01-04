#------------------------------------------
#-- protocol base.py protocol wizard
#------------------------------------------
# protocols/base.py

from abc import ABC, abstractmethod
from typing import Any, Dict, List

class BaseProtocolClient(ABC):
    """Abstract base for protocol clients."""
    
    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection."""
        pass
    
    @abstractmethod
    async def read(self, address: str, **kwargs) -> Any:
        """Read value from address."""
        pass
    
    @abstractmethod
    async def write(self, address: str, value: Any, **kwargs) -> bool:
        """Write value to address."""
        pass
    
    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Connection status."""
        pass


class BaseProtocolCoordinator(DataUpdateCoordinator, ABC):
    """Abstract coordinator for any protocol."""
    
    def __init__(self, hass, client: BaseProtocolClient, config_entry, ...):
        super().__init__(hass, _LOGGER, ...)
        self.client = client
        self.protocol_name = "unknown"
    
    @abstractmethod
    async def _async_update_data(self) -> Dict[str, Any]:
        """Protocol-specific polling logic."""
        pass
    
    @abstractmethod
    def _decode_value(self, raw_value: Any, register_config: dict) -> Any:
        """Protocol-specific decoding."""
        pass
    
    @abstractmethod
    def _encode_value(self, value: Any, register_config: dict) -> Any:
        """Protocol-specific encoding."""
        pass
