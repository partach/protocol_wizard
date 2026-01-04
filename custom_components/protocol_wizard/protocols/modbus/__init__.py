#------------------------------------------
#-- protocol modbus init.py protocol wizard
#------------------------------------------
# protocols/modbus/__init__.py

from ..base import BaseProtocolCoordinator
from .. import ProtocolRegistry

@ProtocolRegistry.register("modbus")
class ModbusCoordinator(BaseProtocolCoordinator):
    """Modbus-specific coordinator."""
    
    def __init__(self, hass, client, config_entry, ...):
        super().__init__(hass, client, config_entry, ...)
        self.protocol_name = "modbus"
    
    async def _async_update_data(self):
        # Your existing Modbus polling logic
        pass
    
    def _decode_value(self, raw_value, register_config):
        # Your existing Modbus decode logic
        pass
