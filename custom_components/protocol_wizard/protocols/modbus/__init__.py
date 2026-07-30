#------------------------------------------
#-- protocol modbus init.py protocol wizard
#------------------------------------------
"""Modbus protocol plugin."""
from .client import ModbusClient
from .const import CONF_REGISTERS, TYPE_SIZES, reg_key
from .coordinator import ModbusCoordinator

__all__ = ["CONF_REGISTERS", "TYPE_SIZES", "ModbusClient", "ModbusCoordinator", "reg_key"]
