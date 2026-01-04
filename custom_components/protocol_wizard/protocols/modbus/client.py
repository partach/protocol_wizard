#------------------------------------------
#-- protocol client.py protocol wizard
#------------------------------------------
"""Modbus protocol client wrapper."""
from __future__ import annotations

import logging
from typing import Any

# from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient, AsyncModbusUdpClient

from ..base import BaseProtocolClient

_LOGGER = logging.getLogger(__name__)


class ModbusClient(BaseProtocolClient):
    """Wrapper for pymodbus clients to match BaseProtocolClient interface."""
    
    def __init__(self, pymodbus_client, slave_id: int):
        """
        Initialize Modbus client wrapper.
        
        Args:
            pymodbus_client: The underlying pymodbus AsyncModbus*Client
            slave_id: Modbus slave/device ID
        """
        self._client = pymodbus_client
        self.slave_id = int(slave_id)
    
    async def connect(self) -> bool:
        """Establish connection."""
        try:
            await self._client.connect()
            return self._client.connected
        except Exception as err:
            _LOGGER.error("Modbus connection failed: %s", err)
            return False
    
    async def disconnect(self) -> None:
        """Close connection."""
        try:
            if self._client.connected:
                self._client.close()
        except Exception as err:
            _LOGGER.debug("Error closing Modbus client: %s", err)
    
    async def read(self, address: str, **kwargs) -> Any:
        """
        Read Modbus register(s).
        
        Kwargs:
            count: Number of registers to read
            register_type: "holding", "input", "coil", "discrete"
        """
        addr = int(address)
        count = kwargs.get("count", 1)
        reg_type = kwargs.get("register_type", "holding")
        
        method_map = {
            "holding": self._client.read_holding_registers,
            "input": self._client.read_input_registers,
            "coil": self._client.read_coils,
            "discrete": self._client.read_discrete_inputs,
        }
        
        method = method_map.get(reg_type)
        if not method:
            raise ValueError(f"Invalid register type: {reg_type}")
        
        result = await method(
            address=addr,
            count=count,
            device_id=self.slave_id,
        )
        
        if result.isError():
            return None
        
        # Return registers or bits depending on type
        if reg_type in ("coil", "discrete"):
            return result.bits[:count]
        return result.registers[:count]
    
    async def write(self, address: str, value: Any, **kwargs) -> bool:
        """
        Write Modbus register(s).
        
        Args:
            address: Register address
            value: Value(s) to write (int or list of ints)
            
        Kwargs:
            register_type: "holding" or "coil" (only writeable types)
        """
        addr = int(address)
        reg_type = kwargs.get("register_type", "holding")
        
        try:
            if reg_type == "holding":
                # value can be int (single register) or list (multiple)
                if isinstance(value, list):
                    result = await self._client.write_registers(
                        address=addr,
                        values=value,
                        device_id=self.slave_id,
                    )
                else:
                    result = await self._client.write_register(
                        address=addr,
                        value=value,
                        device_id=self.slave_id,
                    )
            elif reg_type == "coil":
                result = await self._client.write_coil(
                    address=addr,
                    value=bool(value),
                    device_id=self.slave_id,
                )
            else:
                raise ValueError(f"Cannot write to {reg_type} registers")
            
            return not result.isError()
            
        except Exception as err:
            _LOGGER.error("Modbus write failed at %s: %s", address, err)
            return False
    
    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._client.connected
    
    # Expose underlying client for protocol-specific methods
    @property
    def raw_client(self):
        """Get the underlying pymodbus client for advanced operations."""
        return self._client
