"""Config flow for Protocol Wizard."""
import asyncio
import logging
from typing import Any

import serial.tools.list_ports
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from pymodbus.client import (
    AsyncModbusSerialClient,
    AsyncModbusTcpClient,
    AsyncModbusUdpClient,
)
from pymodbus.exceptions import ModbusIOException

from .const import (
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_CONNECTION_TYPE,
    CONF_FIRST_REG,
    CONF_FIRST_REG_SIZE,
    CONF_HOST,
    CONF_IP,
    CONF_NAME,
    CONF_PARITY,
    CONF_PORT,
    CONF_PROTOCOL,
    CONF_PROTOCOL_BACNET,
    CONF_PROTOCOL_MODBUS,
    CONF_PROTOCOL_MQTT,
    CONF_PROTOCOL_SNMP,
    CONF_SERIAL_PORT,
    CONF_SLAVE_ID,
    CONF_SLAVES,
    CONF_STOPBITS,
    CONF_TEMPLATE,
    CONF_UPDATE_INTERVAL,
    CONNECTION_TYPE_IP,
    CONNECTION_TYPE_SERIAL,
    CONNECTION_TYPE_TCP,
    CONNECTION_TYPE_UDP,
    DEFAULT_BAUDRATE,
    DEFAULT_BYTESIZE,
    DEFAULT_PARITY,
    DEFAULT_SLAVE_ID,
    DEFAULT_STOPBITS,
    DEFAULT_TCP_PORT,
    DOMAIN,
)
from .options_flow import ProtocolWizardOptionsFlow
from .protocols import ProtocolRegistry
from .protocols.mqtt import CONF_BROKER, CONF_PASSWORD, CONF_USERNAME, DEFAULT_PORT
from .template_utils import (
    get_available_templates,
    get_template_dropdown_choices,
    load_template,
)

_LOGGER = logging.getLogger(__name__)
# Reduce noise from pymodbus
# Setting parent logger to CRITICAL to catch all sub-loggers
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
logging.getLogger("pymodbus.logging").setLevel(logging.CRITICAL)

class ProtocolWizardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Protocol Wizard."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._protocol: str = CONF_PROTOCOL_MODBUS
        self._selected_template: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Get the options flow for this handler."""
        return ProtocolWizardOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """First step: protocol selection."""
        available_protocols = ProtocolRegistry.available_protocols()

        if user_input is not None:
            self._protocol = user_input.get(CONF_PROTOCOL, CONF_PROTOCOL_MODBUS)

            if self._protocol == CONF_PROTOCOL_MODBUS:
                return await self.async_step_modbus_common()
            elif self._protocol == CONF_PROTOCOL_SNMP:
                return await self.async_step_snmp_common()
            elif self._protocol == CONF_PROTOCOL_MQTT:
                return await self.async_step_mqtt_common()
            elif self._protocol == CONF_PROTOCOL_BACNET:
                return await self.async_step_bacnet_common()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_PROTOCOL, default=CONF_PROTOCOL_MODBUS): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=proto,
                                label=proto.upper() if proto in (CONF_PROTOCOL_SNMP, CONF_PROTOCOL_MQTT) else proto.title()
                            )
                            for proto in sorted(available_protocols)
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }),
        )

    # ================================================================
    # MODBUS CONFIG FLOW — Step 1: Hub setup (connection only)
    # ================================================================

    async def _get_available_templates(self) -> dict[str, str]:
        """Get available templates for dropdown."""
        templates = await get_available_templates(self.hass, self._protocol)
        return get_template_dropdown_choices(templates)

    async def _load_template_params(self, template_id: str) -> tuple[int, int]:
        """Load first register address and size from template."""
        entities = await load_template(self.hass, self._protocol, template_id)

        if not entities or len(entities) == 0:
            return 0, 1

        first = entities[0]
        address = first.get("address", 0)
        size = first.get("size", 1)
        return address, size

    async def async_step_modbus_common(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Modbus Step 1: Hub settings — name, connection type, update interval."""
        self._protocol = CONF_PROTOCOL_MODBUS
        errors = {}

        if user_input is not None:
            self._data.update(user_input)
            self._data[CONF_PROTOCOL] = CONF_PROTOCOL_MODBUS

            # Proceed to connection-specific settings
            if user_input[CONF_CONNECTION_TYPE] == CONNECTION_TYPE_SERIAL:
                return await self.async_step_modbus_serial()
            return await self.async_step_modbus_ip()

        # Build schema — hub-level settings only
        schema_dict = {
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
            vol.Required(CONF_UPDATE_INTERVAL, default=10): vol.All(
                vol.Coerce(int),
                vol.Range(min=5, max=300),
            ),
        }

        return self.async_show_form(
            step_id="modbus_common",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    # ================================================================
    # MODBUS CONFIG FLOW — Step 2: Connection details
    # ================================================================

    async def async_step_modbus_serial(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Modbus Step 2a: Serial-specific settings."""
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
            self._data.update({
                CONF_SERIAL_PORT: user_input[CONF_SERIAL_PORT],
                CONF_BAUDRATE: user_input[CONF_BAUDRATE],
                CONF_PARITY: user_input[CONF_PARITY],
                CONF_STOPBITS: user_input[CONF_STOPBITS],
                CONF_BYTESIZE: user_input[CONF_BYTESIZE],
            })
            # Proceed to device setup
            return await self.async_step_modbus_device()

        return self.async_show_form(
            step_id="modbus_serial",
            data_schema=vol.Schema({
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

    async def async_step_modbus_ip(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Modbus Step 2b: TCP/UDP-specific settings."""
        errors = {}

        if user_input is not None:
            self._data.update({
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input[CONF_PORT],
                CONF_IP: user_input[CONF_IP],
            })
            # Proceed to device setup
            return await self.async_step_modbus_device()

        return self.async_show_form(
            step_id="modbus_ip",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_TCP_PORT): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Required(CONF_IP, default=CONNECTION_TYPE_TCP): selector.SelectSelector(
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

    # ================================================================
    # MODBUS CONFIG FLOW — Step 3: First device (slave) setup
    # ================================================================

    async def async_step_modbus_device(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Modbus Step 3: First device — slave ID, name, template, test register."""
        errors = {}

        if user_input is not None:
            slave_id = int(user_input[CONF_SLAVE_ID])
            device_name = user_input.get("device_name") or f"Slave {slave_id}"

            # Handle template selection
            self._selected_template = None
            use_template = user_input.get("use_template", False)
            if use_template:
                template_name = user_input.get(CONF_TEMPLATE)
                if template_name:
                    self._selected_template = template_name
                    # Auto-fill test parameters from template if not set
                    addr, size = await self._load_template_params(template_name)
                    if user_input.get(CONF_FIRST_REG) == 0:
                        user_input[CONF_FIRST_REG] = addr
                    if user_input.get(CONF_FIRST_REG_SIZE) == 1:
                        user_input[CONF_FIRST_REG_SIZE] = size

            # Build final data for connection test
            final_data = dict(self._data)
            final_data[CONF_SLAVE_ID] = slave_id
            final_data[CONF_FIRST_REG] = user_input.get(CONF_FIRST_REG, 0)
            final_data[CONF_FIRST_REG_SIZE] = user_input.get(CONF_FIRST_REG_SIZE, 1)

            # Set unique ID based on connection - must be outside try/except to properly abort
            if final_data.get(CONF_CONNECTION_TYPE) == CONNECTION_TYPE_SERIAL:
                unique_id = f"modbus_serial_{final_data[CONF_SERIAL_PORT]}"
            else:
                unique_id = f"modbus_ip_{final_data[CONF_HOST]}_{final_data[CONF_PORT]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                await self._async_test_modbus_connection(final_data)

                # Build first slave entry
                first_slave = {
                    "slave_id": slave_id,
                    "name": device_name,
                    "registers": [],
                }
                if self._selected_template:
                    first_slave["template"] = self._selected_template

                # Create entry — hub data in entry.data, slave in options
                hub_data = {k: v for k, v in final_data.items()
                            if k not in (CONF_SLAVE_ID, CONF_FIRST_REG, CONF_FIRST_REG_SIZE)}

                return self.async_create_entry(
                    title=final_data.get(CONF_NAME, "Modbus Hub"),
                    data=hub_data,
                    options={
                        CONF_SLAVES: [first_slave],
                    },
                )

            except (ModbusIOException, OSError, ConnectionError, TimeoutError):
                _LOGGER.exception("Connection test failed")
                errors["base"] = "cannot_connect"

        # Get available templates
        templates = await self._get_available_templates()
        template_options = [
            selector.SelectOptionDict(value=t, label=t)
            for t in templates
        ]

        # Build schema
        schema_dict = {
            vol.Required(CONF_SLAVE_ID, default=DEFAULT_SLAVE_ID): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=255,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional("device_name", default=""): str,
        }

        # Add template option if templates exist
        if templates:
            schema_dict[vol.Optional("use_template", default=False)] = selector.BooleanSelector()
            schema_dict[vol.Optional(CONF_TEMPLATE)] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=template_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        # Add test parameters
        schema_dict.update({
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
        })

        return self.async_show_form(
            step_id="modbus_device",
            data_schema=vol.Schema(schema_dict),
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
                    timeout=3,
                    retries=1,
                )
            elif data[CONF_CONNECTION_TYPE] == CONNECTION_TYPE_IP and data.get(CONF_IP) == CONNECTION_TYPE_UDP:
                client = AsyncModbusUdpClient(
                    host=data[CONF_HOST],
                    port=data[CONF_PORT],
                    timeout=3,
                    retries=1,
                )
            else:
                client = AsyncModbusTcpClient(
                    host=data[CONF_HOST],
                    port=data[CONF_PORT],
                    timeout=3,
                    retries=1,
                )

            await client.connect()
            if not client.connected:
                raise ConnectionError("Failed to connect to Modbus device")

            address = int(data[CONF_FIRST_REG])
            count = int(data[CONF_FIRST_REG_SIZE])
            slave_id = int(data[CONF_SLAVE_ID])

            methods = [
                ("input registers", client.read_input_registers),
                ("holding registers", client.read_holding_registers),
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
                except (ModbusIOException, OSError, ConnectionError, TimeoutError) as inner_err:
                    _LOGGER.debug("Test read failed for %s at addr %d: %s", name, address, inner_err)

            if not success:
                _LOGGER.debug(
                    "Could not read %d value(s) from address %d using any register type. "
                    "Check address, size, slave ID, or device compatibility.",
                    count, address
                )

        finally:
            if client:
                try:
                    client.close()
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Error closing Modbus client: %s", err)

    # ================================================================
    # SNMP CONFIG FLOW
    # ================================================================

    async def async_step_snmp_common(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """SNMP: Connection settings and test."""
        self._protocol = CONF_PROTOCOL_SNMP
        errors = {}

        if user_input is not None:
            final_data = {
                CONF_PROTOCOL: CONF_PROTOCOL_SNMP,
                CONF_NAME: user_input[CONF_NAME],
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input.get(CONF_PORT, 161),
                "community": user_input["community"],
                "version": user_input["version"],
                CONF_UPDATE_INTERVAL: user_input.get(CONF_UPDATE_INTERVAL, 30),
            }

            # Set unique ID based on host - must be outside try/except to properly abort
            unique_id = f"snmp_{final_data[CONF_HOST]}_{final_data[CONF_PORT]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                # Test SNMP connection
                await self._async_test_snmp_connection(final_data)

                # Handle template if selected
                options = {}
                use_template = user_input.get("use_template", False)
                if use_template and user_input.get(CONF_TEMPLATE):
                    options[CONF_TEMPLATE] = user_input[CONF_TEMPLATE]

                return self.async_create_entry(
                    title=f"SNMP {final_data[CONF_HOST]}",
                    data=final_data,
                    options=options,
                )

            except (OSError, ConnectionError, TimeoutError):
                _LOGGER.exception("SNMP connection test failed")
                errors["base"] = "cannot_connect"

        # Get available templates
        templates = await self._get_available_templates()
        template_options = [
            selector.SelectOptionDict(value=t, label=t)
            for t in templates
        ]

        schema_dict = {
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
        }

        # Add template option if templates exist
        if templates:
            schema_dict[vol.Optional("use_template", default=False)] = selector.BooleanSelector()
            schema_dict[vol.Optional(CONF_TEMPLATE)] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=template_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        return self.async_show_form(
            step_id="snmp_common",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    # ================================================================
    # BACNET CONFIG FLOW
    # ================================================================

    async def async_step_bacnet_common(self, user_input=None):
        """Choose BACnet connection method."""
        self._protocol = CONF_PROTOCOL_BACNET
        if user_input:
            if user_input["method"] == "discover":
                return await self.async_step_bacnet_discover()
            else:
                return await self.async_step_bacnet_manual()

        return self.async_show_form(
            step_id="bacnet_common",
            data_schema=vol.Schema({
                vol.Required("method", default="manual"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "discover", "label": "Discover Devices (Recommended)"},
                            {"value": "manual", "label": "Manual Entry"},
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }),
            description_placeholders={
                "info": "BACnet/IP device discovery uses Who-Is broadcast to find devices on your network."
            }
        )


    async def async_step_bacnet_discover(self, user_input=None):
        """Discover BACnet devices on the network."""
        if user_input:
            # User selected a device from discovery
            device = user_input.get("device")
            if device:
                # Parse device string: "Device Name (192.168.1.100:47808, ID: 12345)"
                import re
                match = re.match(r".*\((.+?):(\d+), ID: (\d+)\)", device)
                if match:
                    host = match.group(1)
                    port = int(match.group(2))
                    device_id = int(match.group(3))

                    # Store for template step
                    self._data = {
                        CONF_HOST: host,
                        CONF_PORT: port,
                        "device_id": device_id,
                        "device_name": f"BACnet Device {device_id}",
                    }
                    return await self.async_step_bacnet_template()

        # Perform discovery
        errors = {}
        discovered_devices = []

        discovery_client = None
        try:
            from .protocols.bacnet.client import BACnetClient

            # Create temporary client for discovery
            discovery_client = BACnetClient(
                self.hass,
                host="0.0.0.0",  # Listen on all interfaces
                device_id=None,   # Discovery mode
                port=47808
            )

            # Run discovery (with timeout)
            _LOGGER.info("Starting BACnet device discovery...")
            discovered = await asyncio.wait_for(
                discovery_client.discover_devices(timeout=10),
                timeout=15
            )

            if discovered:
                for device in discovered:
                    label = f"{device.get('name', 'Unknown')} ({device['address']}:{device['port']}, ID: {device['device_id']})"
                    discovered_devices.append({
                        "value": label,
                        "label": label
                    })

                _LOGGER.info("Discovered %d BACnet devices", len(discovered_devices))
            else:
                _LOGGER.warning("No BACnet devices discovered")
                errors["base"] = "no_devices_found"

        except asyncio.TimeoutError:
            _LOGGER.warning("BACnet discovery timed out")
            errors["base"] = "discovery_timeout"
        except (OSError, ConnectionError, TimeoutError) as err:
            _LOGGER.error("BACnet discovery failed: %s", err)
            errors["base"] = "discovery_failed"
        finally:
            if discovery_client:
                try:
                    await discovery_client.disconnect()
                    _LOGGER.info("Discovery client disconnected")
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Error disconnecting discovery client: %s", err)

        # If no devices found or error, show option to go manual
        if not discovered_devices or errors:
            return self.async_show_form(
                step_id="bacnet_discover",
                data_schema=vol.Schema({
                    vol.Required("retry", default=False): bool,
                }),
                errors=errors,
                description_placeholders={
                    "count": "0"
                }
            )

        # Show discovered devices
        return self.async_show_form(
            step_id="bacnet_discover",
            data_schema=vol.Schema({
                vol.Required("device"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=discovered_devices,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
            description_placeholders={
                "count": str(len(discovered_devices))
            }
        )


    async def async_step_bacnet_manual(self, user_input=None, errors=None):
        """Manual BACnet/IP configuration."""
        errors = errors or {}

        if user_input:
            host = user_input[CONF_HOST].strip()
            device_id = user_input["device_id"]
            port = user_input.get(CONF_PORT, 47808)
            network_number = user_input.get("network_number", 0)
            device_name = user_input.get(CONF_NAME) or f"BACnet Device {device_id}"

            if not host:
                errors[CONF_HOST] = "required"

            if not errors:
                # Store for template step
                self._data = {
                    CONF_HOST: host,
                    CONF_PORT: port,
                    "device_id": device_id,
                    "device_name": device_name,
                    "network_number": network_number,
                }
                return await self.async_step_bacnet_template()

        # Show manual entry form
        return self.async_show_form(
            step_id="bacnet_manual",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default="BACnet Device"): str,
                vol.Required(CONF_HOST): str,
                vol.Required("device_id"): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=0, max=4194303)
                ),
                vol.Optional(CONF_PORT, default=47808): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=1, max=65535)
                ),
                vol.Optional("network_number"): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=0, max=65535)
                ),
            }),
            errors=errors,
            description_placeholders={
                "info": (
                    "Enter BACnet/IP device details. "
                    "Device ID is the BACnet device instance (0-4194303). "
                    "Port is usually 47808. "
                    "Network number is optional (leave empty for local network)."
                )
            }
        )

    async def async_step_bacnet_template(self, user_input=None):
        """BACnet: Optional template selection before creating entry."""
        errors = {}

        if user_input is not None:
            # Handle template selection
            use_template = user_input.get("use_template", False)
            template_name = None
            if use_template:
                template_name = user_input.get(CONF_TEMPLATE)

            host = self._data[CONF_HOST]
            port = self._data[CONF_PORT]
            device_id = self._data["device_id"]
            device_name = self._data.get("device_name", f"BACnet Device {device_id}")
            network_number = self._data.get("network_number", 0)

            # Set unique ID based on host and device
            unique_id = f"bacnet_{host}_{port}_{device_id}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            # Test connection
            try:
                from .protocols.bacnet.client import BACnetClient
                client = BACnetClient(self.hass, host, device_id, port, network_number)

                if await client.connect():
                    device_config = {
                        "device_id": device_id,
                        "address": host,
                        "port": port,
                        "name": device_name,
                        "entities": [],
                        "template_applied": False,
                    }
                    if template_name:
                        device_config["template"] = template_name

                    return self.async_create_entry(
                        title=f"BACnet Network ({host})",
                        data={
                            CONF_PROTOCOL: CONF_PROTOCOL_BACNET,
                            CONF_NAME: "BACnet Network",
                            CONF_PORT: port,
                            "network_number": network_number,
                        },
                        options={
                            "bacnet_devices": [device_config]
                        },
                    )
                else:
                    errors["base"] = "cannot_connect"
            except (OSError, ConnectionError, TimeoutError) as err:
                _LOGGER.error("BACnet connection test failed: %s", err)
                errors["base"] = "unknown"

            if errors:
                return await self.async_step_bacnet_manual(user_input=None, errors=errors)

        # Get available templates
        templates = await self._get_available_templates()
        template_options = [
            selector.SelectOptionDict(value=t, label=t)
            for t in templates
        ]

        schema_dict = {}
        if templates:
            schema_dict[vol.Optional("use_template", default=False)] = selector.BooleanSelector()
            schema_dict[vol.Optional(CONF_TEMPLATE)] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=template_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        # If no templates, just show a confirm button
        if not schema_dict:
            schema_dict[vol.Optional("use_template", default=False)] = selector.BooleanSelector()

        return self.async_show_form(
            step_id="bacnet_template",
            data_schema=vol.Schema(schema_dict),
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
            if not await client.connect():
                raise ConnectionError("Failed to connect to SNMP device")
        finally:
            await client.disconnect()

    async def async_step_mqtt_common(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """MQTT: Broker connection settings and test."""
        self._protocol = CONF_PROTOCOL_MQTT
        errors = {}

        if user_input is not None:
            final_data = {
                CONF_PROTOCOL: CONF_PROTOCOL_MQTT,
                CONF_NAME: user_input[CONF_NAME],
                CONF_BROKER: user_input[CONF_BROKER],
                CONF_PORT: user_input.get(CONF_PORT, DEFAULT_PORT),
                CONF_USERNAME: user_input.get(CONF_USERNAME, ""),
                CONF_PASSWORD: user_input.get(CONF_PASSWORD, ""),
                CONF_UPDATE_INTERVAL: user_input.get(CONF_UPDATE_INTERVAL, 30),
            }

            # Set unique ID based on broker - must be outside try/except to properly abort
            unique_id = f"mqtt_{final_data[CONF_BROKER]}_{final_data[CONF_PORT]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                # Test MQTT connection
                await self._async_test_mqtt_connection(final_data)

                # Handle template if selected
                options = {}
                use_template = user_input.get("use_template", False)
                if use_template and user_input.get(CONF_TEMPLATE):
                    options[CONF_TEMPLATE] = user_input[CONF_TEMPLATE]

                return self.async_create_entry(
                    title=f"MQTT {final_data[CONF_BROKER]}",
                    data=final_data,
                    options=options,
                )

            except (OSError, ConnectionError, TimeoutError):
                _LOGGER.exception("MQTT connection test failed")
                errors["base"] = "cannot_connect"

        # Get available templates
        templates = await self._get_available_templates()
        template_options = [
            selector.SelectOptionDict(value=t, label=t)
            for t in templates
        ]

        schema_dict = {
            vol.Required(CONF_NAME, default="MQTT Device"): str,
            vol.Required(CONF_BROKER): str,
            vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Optional(CONF_USERNAME): str,
            vol.Optional(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_UPDATE_INTERVAL, default=30): vol.All(
                vol.Coerce(int), vol.Range(min=5, max=300)
            ),
        }

        # Add template selection if templates exist
        if template_options:
            schema_dict[vol.Optional("use_template", default=False)] = bool
            schema_dict[vol.Optional(CONF_TEMPLATE)] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=template_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        return self.async_show_form(
            step_id="mqtt_common",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={
                "broker_help": "Hostname or IP address of MQTT broker",
                "port_help": "Default is 1883 (unencrypted) or 8883 (TLS)",
            },
        )

    async def _async_test_mqtt_connection(self, config: dict) -> None:
        """Test MQTT broker connection."""
        from .protocols.mqtt import MQTTClient

        client = None
        try:
            client = MQTTClient(
                broker=config[CONF_BROKER],
                port=config[CONF_PORT],
                username=config.get(CONF_USERNAME) or None,
                password=config.get(CONF_PASSWORD) or None,
                timeout=10.0,
            )

            connected = await client.connect()

            if not connected:
                raise ConnectionError("Could not connect to MQTT broker")

            _LOGGER.info("MQTT connection test successful to %s:%s",
                        config[CONF_BROKER], config[CONF_PORT])

        except (OSError, ConnectionError, TimeoutError) as err:
            _LOGGER.error("MQTT connection test failed: %s", err)
            raise ConnectionError(
                f"Cannot connect to MQTT broker at {config[CONF_BROKER]}:{config[CONF_PORT]}. "
                "Check broker address, port, and credentials."
            ) from err

        finally:
            if client:
                try:
                    await client.disconnect()
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Error disconnecting MQTT client: %s", err)
