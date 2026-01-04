#------------------------------------------
#-- protocol init.py protocol wizard
#------------------------------------------
# protocols/__init__.py

from typing import Dict, Type
from .base import BaseProtocolClient, BaseProtocolCoordinator

class ProtocolRegistry:
    """Registry of available protocols."""
    
    _protocols: Dict[str, Type[BaseProtocolCoordinator]] = {}
    
    @classmethod
    def register(cls, protocol_name: str):
        """Decorator to register a protocol."""
        def wrapper(coordinator_class):
            cls._protocols[protocol_name] = coordinator_class
            return coordinator_class
        return wrapper
    
    @classmethod
    def get_coordinator_class(cls, protocol_name: str):
        """Get coordinator class for protocol."""
        return cls._protocols.get(protocol_name)
    
    @classmethod
    def available_protocols(cls) -> List[str]:
        """List all registered protocols."""
        return list(cls._protocols.keys())
