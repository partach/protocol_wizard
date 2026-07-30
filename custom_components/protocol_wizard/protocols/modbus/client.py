#------------------------------------------
#-- protocol client.py protocol wizard
#------------------------------------------
"""Modbus protocol client wrapper."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from pymodbus.exceptions import ModbusIOException

from ..base import BaseProtocolClient

_LOGGER = logging.getLogger(__name__)
# Reduce noise from pymodbus
# Setting parent logger to CRITICAL to catch all sub-loggers
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
logging.getLogger("pymodbus.logging").setLevel(logging.CRITICAL)

# Shared connection state - keyed by pymodbus client id
# This ensures all ModbusClient wrappers sharing the same pymodbus client
# see the same connection state
_CONNECTION_STATE: dict[int, dict] = {}


def _get_connection_state(pymodbus_client) -> dict:
    """Get or create shared connection state for a pymodbus client."""
    client_id = id(pymodbus_client)
    if client_id not in _CONNECTION_STATE:
        _CONNECTION_STATE[client_id] = {
            "failed": False,
            "reconnecting": False,
            "lock": asyncio.Lock(),  # Per-connection reconnection lock
        }
    return _CONNECTION_STATE[client_id]


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
        # Get shared connection state for this pymodbus client
        self._conn_state = _get_connection_state(pymodbus_client)

    async def connect(self) -> bool:
        """Establish connection."""
        try:
            if not self._client.connected:
                await self._client.connect()
            self._conn_state["failed"] = False
            return self._client.connected
        except Exception as err:
            _LOGGER.error("Modbus connection failed: %s", err)
            self._conn_state["failed"] = True
            return False

    async def disconnect(self) -> None:
        """Close connection."""
        try:
            if self._client.connected:
                self._client.close()
            self._conn_state["failed"] = False
        except Exception as err:
            _LOGGER.debug("Error closing Modbus client: %s", err)

    async def reconnect(self) -> bool:
        """Force reconnection - close and reopen.

        Uses a lock to ensure only one reconnection happens at a time
        across all slaves sharing this connection.
        """
        # Use the shared reconnection lock to prevent multiple simultaneous reconnects
        async with self._conn_state["lock"]:
            # Double-check if still needed (another slave might have reconnected)
            if not self._conn_state["failed"] and self._client.connected:
                _LOGGER.debug("Connection already recovered by another slave")
                return True

            if self._conn_state["reconnecting"]:
                _LOGGER.debug("Reconnection already in progress, waiting...")
                # Wait a bit for the other reconnection to complete
                await asyncio.sleep(1.0)
                return self._client.connected

            self._conn_state["reconnecting"] = True
            _LOGGER.info("Forcing Modbus reconnection (slave %d)...", self.slave_id)

            try:
                # Force close regardless of state
                try:
                    self._client.close()
                except Exception:
                    pass

                # Small delay before reconnecting
                await asyncio.sleep(0.3)

                # Reconnect
                await self._client.connect()
                self._conn_state["failed"] = False
                _LOGGER.info("Modbus reconnection successful")
                return self._client.connected
            except Exception as err:
                _LOGGER.error("Modbus reconnection failed: %s", err)
                self._conn_state["failed"] = True
                return False
            finally:
                self._conn_state["reconnecting"] = False

    async def read(self, address: str, **kwargs) -> Any:
        """
        Read Modbus register(s).

        Kwargs:
            count: Number of registers to read
            register_type: "holding", "input", "coil", "discrete"
        """
        addr = int(address)
        count = int(kwargs.get("count", 1))
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

        try:
            result = await method(
                address=addr,
                count=count,
                device_id=int(self.slave_id),
            )

            if result.isError():
                return None

            # Success - mark connection as healthy (shared state)
            self._conn_state["failed"] = False

            # Return registers or bits depending on type
            if reg_type in ("coil", "discrete"):
                return result.bits[:count]
            return result.registers[:count]

        except ModbusIOException as err:
            _LOGGER.warning("Modbus I/O error reading address %s (slave %d): %s",
                          address, self.slave_id, err)
            self._conn_state["failed"] = True  # Mark shared state for reconnection
            raise  # Re-raise so coordinator can handle
        except Exception as err:
            _LOGGER.error("Modbus read error at %s (slave %d): %s",
                         address, self.slave_id, err)
            self._conn_state["failed"] = True
            raise

    async def write(self, address: str, value: Any, **kwargs) -> bool:
        addr = int(address)
        reg_type = kwargs.get("register_type", "holding").lower()
        try:
            if reg_type == "coil":
                if isinstance(value, list):
                    result = await self._client.write_coils(
                        address=addr,
                        values=[bool(v) for v in value],
                        device_id=self.slave_id,
                    )
                else:
                    result = await self._client.write_coil(
                        address=addr,
                        value=bool(value),
                        device_id=self.slave_id,
                    )
            elif reg_type == "holding":
                if isinstance(value, list) and len(value) > 1:
                    result = await self._client.write_registers(
                        address=addr,
                        values=[int(v) for v in value],
                        device_id=self.slave_id,
                    )
                else:
                    single_val = value[0] if isinstance(value, list) else value
                    result = await self._client.write_register(
                        address=addr,
                        value=int(single_val),
                        device_id=self.slave_id,
                    )
            elif reg_type in ("input", "discrete"):
                _LOGGER.error("Cannot write to read-only %s registers", reg_type)
                return False
            else:
                _LOGGER.error("Unsupported register_type '%s'", reg_type)
                return False

            success = not result.isError()
            if success:
                self._conn_state["failed"] = False
            return success

        except ModbusIOException as err:
            _LOGGER.warning("Modbus I/O error writing to %s (slave %d): %s",
                          address, self.slave_id, err)
            self._conn_state["failed"] = True
            return False
        except Exception as err:
            _LOGGER.error("Modbus write failed at %s (slave %d): %s",
                         address, self.slave_id, err)
            self._conn_state["failed"] = True
            return False

    @property
    def is_connected(self) -> bool:
        """Check if connected and healthy (uses shared state)."""
        if self._conn_state["failed"]:
            return False
        return self._client.connected

    @property
    def needs_reconnect(self) -> bool:
        """Check if reconnection is needed due to errors (uses shared state)."""
        return self._conn_state["failed"]

    # Expose underlying client for protocol-specific methods
    @property
    def raw_client(self):
        """Get the underlying pymodbus client for advanced operations."""
        return self._client
