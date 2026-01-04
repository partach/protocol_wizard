#------------------------------------------
#-- protocol modbus init.py protocol wizard
#------------------------------------------
"""Modbus protocol plugin."""
from .coordinator import ModbusCoordinator
from .client import ModbusClient
from .const import CONF_ENTITIES, TYPE_SIZES, reg_key

__all__ = ["ModbusCoordinator", "ModbusClient", "CONF_ENTITIES", "TYPE_SIZES", "reg_key"]
