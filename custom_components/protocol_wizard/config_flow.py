#------------------------------------------
#-- base config_flow.py protocol wizard
#------------------------------------------
"""Config flow for Protocol Wizard."""
import logging
from typing import Any
import serial.tools.list_ports
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.data_entry_flow import FlowResult
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient, AsyncModbusUdpClient
from pymodbus.framer import FramerType
from pymodbus.exceptions import ModbusException

from .const import (
    CONNECTION_TYPE_SERIAL,
    CONNECTION_TYPE_IP,
    CONNECTION_TYPE_TCP,
    CONNECTION_TYPE_UDP,
    CONF_CONNECTION_TYPE,
    CONF_HOST,
    CONF_PORT,
    CONF_SERIAL_PORT,
    CONF_SLAVE_ID,
    CONF_BAUDRATE,
    CONF_PARITY,
    CONF_NAME,
    CONF_STOPBITS,
    CONF_BYTESIZE,
    CONF_FIRST_REG,
    CONF_FIRST_REG_SIZE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_SLAVE_ID,
    DEFAULT_BAUDRATE,
    DEFAULT_TCP_PORT,
    DEFAULT_PARITY,
    DEFAULT_STOPBITS,
    DEFAULT_BYTESIZE,
    DOMAIN,
    CONF_PROTOCOL_MODBUS,
    CONF_PROTOCOL_SNMP,
    CONF_PROTOCOL,
)
from .options_flow import ProtocolWizardOptionsFlow
from .protocols import ProtocolRegistry

_LOGGER = logging.getLogger(__name__)


class ProtocolWizardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Protocol Wizard."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._protocol: str = CONF_PROTOCOL_MODBUS  # Default to modbus for now

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Get the options flow for this handler."""
        return ProtocolWizardOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """First step: protocol selection."""
        available_protocols = ProtocolRegistry.available_protocols()
        
        # If user selected a protocol
        if user_input is not None:
            self._protocol = user_input.get(CONF_PROTOCOL, CONF_PROTOCOL_MODBUS)
            
            if self._protocol == CONF_PROTOCOL_MODBUS:
                return await self.async_step_modbus_common()
            elif self._protocol == CONF_PROTOCOL_SNMP:
                return await self.async_step_snmp_common()
            
        # Show protocol selection
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_PROTOCOL, default=CONF_PROTOCOL_MODBUS): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=proto,
                                label=proto.upper() if proto == CONF_PROTOCOL_SNMP else proto.title()
                            )
                            for proto in sorted(available_protocols)
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }),
        )

    # ================================================================
    # MODBUS CONFIG FLOW
    # ================================================================
    
    async def async_step_modbus_common(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Modbus: Common settings and first register test."""
        if user_input is not None:
            self._data.update(user_input)
            self._data[CONF_PROTOCOL] = CONF_PROTOCOL_MODBUS  # Ensure protocol is set
            
            if user_input[CONF_CONNECTION_TYPE] == CONNECTION_TYPE_SERIAL:
                return await self.async_step_modbus_serial()
            return await self.async_step_modbus_tcp()
        
        return self.async_show_form(
            step_id="modbus_common",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default="Modbus Hub"): str,
                vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_TYPE_SERIAL): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=CONNECTION_TYPE_SERIAL, label="Serial (RS485/RTU)"),
                            selector.SelectOptionDict(value=CONNECTION_TYPE_IP, label="IP (Modbus TCP/UDP)"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_SLAVE_ID, default=DEFAULT_SLAVE_ID): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=255,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_FIRST_REG, default=0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=65535,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_FIRST_REG_SIZE, default=1): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=20,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_UPDATE_INTERVAL, default=10): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=5, max=300),
                ),
            }),
        )

    async def async_step_modbus_serial(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Modbus: Serial-specific settings."""
        errors = {}

        ports = await self.hass.async_add_executor_job(serial.tools.list_ports.comports)
        port_options = [
            selector.SelectOptionDict(
                value=port.device,
                label=f"{port.device} - {port.description or 'Unknown'}"
                      + (f" ({port.manufacturer})" if port.manufacturer else ""),
            )
            for port in ports
        ]
        port_options.sort(key=lambda opt: opt["value"])

        if user_input is not None:
            try:
                final_data = {
                    **self._data,
                    CONF_SERIAL_PORT: user_input[CONF_SERIAL_PORT],
                    CONF_BAUDRATE: user_input[CONF_BAUDRATE],
                    CONF_PARITY: user_input[CONF_PARITY],
                    CONF_STOPBITS: user_input[CONF_STOPBITS],
                    CONF_BYTESIZE: user_input[CONF_BYTESIZE],
                }

                await self._async_test_modbus_connection(final_data)

                return self.async_create_entry(
                    title=final_data[CONF_NAME],
                    data=final_data
                )

            except Exception as err:
                _LOGGER.exception("Serial connection test failed: %s", err)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="modbus_serial",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=self._data.get(CONF_NAME, "Modbus Hub")): str,
                vol.Required(CONF_SERIAL_PORT): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=port_options,
                        mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.In([2400, 4800, 9600, 19200, 38400]),
                vol.Required(CONF_PARITY, default=DEFAULT_PARITY): vol.In(["N", "E", "O"]),
                vol.Required(CONF_STOPBITS, default=DEFAULT_STOPBITS): vol.In([1, 2]),
                vol.Required(CONF_BYTESIZE, default=DEFAULT_BYTESIZE): vol.In([7, 8]),
            }),
            errors=errors,
        )

    async def async_step_modbus_tcp(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Modbus: TCP/UDP-specific settings."""
        errors = {}

        if user_input is not None:
            try:
                final_data = {
                    **self._data,
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_PORT: user_input[CONF_PORT],
                    CONF_PROTOCOL: user_input[CONF_PROTOCOL],
                }

                await self._async_test_modbus_connection(final_data)

                return self.async_create_entry(
                    title=final_data[CONF_NAME],
                    data=final_data
                )

            except Exception as err:
                _LOGGER.exception("TCP connection test failed: %s", err)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="modbus_tcp",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=self._data.get(CONF_NAME, "Modbus Hub")): str,
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_TCP_PORT): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Required(CONF_PROTOCOL, default=CONNECTION_TYPE_TCP): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=CONNECTION_TYPE_TCP, label="TCP"),
                            selector.SelectOptionDict(value=CONNECTION_TYPE_UDP, label="UDP"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
            errors=errors,
        )

    async def _async_test_modbus_connection(self, data: dict[str, Any]) -> None:
        """Test Modbus connection and read first register."""
        client = None
        try:
            if data[CONF_CONNECTION_TYPE] == CONNECTION_TYPE_SERIAL:
                client = AsyncModbusSerialClient(
                    port=data[CONF_SERIAL_PORT],
                    baudrate=data[CONF_BAUDRATE],
                    parity=data.get(CONF_PARITY, DEFAULT_PARITY),
                    stopbits=data.get(CONF_STOPBITS, DEFAULT_STOPBITS),
                    bytesize=data.get(CONF_BYTESIZE, DEFAULT_BYTESIZE),
                    timeout=5,
                )
            elif data[CONF_CONNECTION_TYPE] == CONNECTION_TYPE_IP and data[CONF_PROTOCOL] == CONNECTION_TYPE_UDP:
                client = AsyncModbusUdpClient(
                    host=data[CONF_HOST],
                    port=data[CONF_PORT],
                    framer=FramerType.SOCKET,
                    timeout=5,
                )
            else:
                client = AsyncModbusTcpClient(
                    host=data[CONF_HOST],
                    port=data[CONF_PORT],
                    framer=FramerType.SOCKET,
                    timeout=5,
                )

            await client.connect()
            if not client.connected:
                raise ConnectionError("Failed to connect to Modbus device")

            address = int(data[CONF_FIRST_REG])
            count = int(data[CONF_FIRST_REG_SIZE])
            slave_id = int(data[CONF_SLAVE_ID])

            methods = [
                ("holding registers", client.read_holding_registers),
                ("input registers", client.read_input_registers),
                ("coils", client.read_coils),
                ("discrete inputs", client.read_discrete_inputs),
            ]

            success = False
            for name, method in methods:
                try:
                    if name in ("coils", "discrete inputs"):
                        result = await method(address=address, count=count, device_id=slave_id)
                        if not result.isError() and hasattr(result, "bits") and len(result.bits) >= count:
                            success = True
                            break
                    else:
                        result = await method(address=address, count=count, device_id=slave_id)
                        if not result.isError() and hasattr(result, "registers") and len(result.registers) == count:
                            success = True
                            break
                except Exception as inner_err:
                    _LOGGER.debug("Test read failed for %s at addr %d: %s", name, address, inner_err)

            if not success:
                raise ModbusException(
                    f"Could not read {count} value(s) from address {address} using any register type. "
                    "Check address, size, slave ID, or device compatibility."
                )

        finally:
            if client:
                try:
                    client.close()
                except Exception as err:
                    _LOGGER.debug("Error closing Modbus client: %s", err)

    # ================================================================
    # SNMP CONFIG FLOW
    # ================================================================
    
    async def async_step_snmp_common(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """SNMP: Connection settings and test."""
        errors = {}
        
        if user_input is not None:
            try:
                final_data = {
                    CONF_PROTOCOL: CONF_PROTOCOL_SNMP,
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_PORT: user_input.get(CONF_PORT, 161),
                    "community": user_input["community"],
                    "version": user_input["version"],
                    CONF_UPDATE_INTERVAL: user_input.get(CONF_UPDATE_INTERVAL, 30),
                }
                
                # Test SNMP connection
                await self._async_test_snmp_connection(final_data)
                
                return self.async_create_entry(
                    title=f"SNMP {final_data[CONF_HOST]}",
                    data=final_data
                )
                
            except Exception as err:
                _LOGGER.exception("SNMP connection test failed: %s", err)
                errors["base"] = "cannot_connect"
        
        return self.async_show_form(
            step_id="snmp_common",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default="SNMP Device"): str,
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_PORT, default=161): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Required("community", default="public"): str,
                vol.Required("version", default="2c"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="1", label="SNMPv1"),
                            selector.SelectOptionDict(value="2c", label="SNMPv2c"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_UPDATE_INTERVAL, default=30): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=10, max=300),
                ),
            }),
            errors=errors,
        )
    
    async def _async_test_snmp_connection(self, data: dict[str, Any]) -> None:
        """Test SNMP connection by reading sysDescr."""
        from .protocols.snmp import SNMPClient
        
        client = SNMPClient(
            host=data[CONF_HOST],
            port=data.get(CONF_PORT, 161),
            community=data["community"],
            version=data["version"],
        )
        
        try:
            # Try to connect (reads sysDescr internally)
            if not await client.connect():
                raise ConnectionError("Failed to connect to SNMP device")
        finally:
            await client.disconnect()
