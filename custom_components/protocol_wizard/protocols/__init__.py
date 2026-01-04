#------------------------------------------
#-- protocol init.py protocol wizard
#------------------------------------------
"""Protocol registry for Protocol Wizard."""
from typing import Dict, Type
from .base import BaseProtocolCoordinator

class ProtocolRegistry:
    """Registry of available protocols."""
    
    _protocols: Dict[str, Type[BaseProtocolCoordinator]] = {}
    
    @classmethod
    def register(cls, protocol_name: str):
        """Decorator to register a protocol coordinator."""
        def wrapper(coordinator_class):
            cls._protocols[protocol_name] = coordinator_class
            return coordinator_class
        return wrapper
    
    @classmethod
    def get_coordinator_class(cls, protocol_name: str) -> Type[BaseProtocolCoordinator] | None:
        """Get coordinator class for protocol."""
        return cls._protocols.get(protocol_name)
    
    @classmethod
    def available_protocols(cls) -> list[str]:
        """List all registered protocols."""
        return list(cls._protocols.keys())
