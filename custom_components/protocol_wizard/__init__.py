#------------------------------------------
#-- base init.py protocol wizard
#------------------------------------------
"""The Protocol Wizard integration."""
import os
import shutil
import logging
from homeassistant.helpers import device_registry as dr
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient, AsyncModbusUdpClient
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service import SupportsResponse
from datetime import timedelta
from .protocols.snmp import SNMPClient

from .const import (
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_CONNECTION_TYPE,
    CONF_HOST,
    CONF_PARITY,
    CONF_PORT,
    CONF_SERIAL_PORT,
    CONF_SLAVE_ID,
    CONF_STOPBITS,
    CONF_UPDATE_INTERVAL,
    CONF_NAME,
    CONNECTION_TYPE_SERIAL,
    CONNECTION_TYPE_IP,
    CONNECTION_TYPE_UDP,
    CONNECTION_TYPE_TCP,
    DEFAULT_BAUDRATE,
    DEFAULT_BYTESIZE,
    DEFAULT_PARITY,
    DEFAULT_STOPBITS,
    DOMAIN,
    CONF_PROTOCOL_MODBUS,
    CONF_PROTOCOL_SNMP,
    CONF_PROTOCOL,
)

# Import protocol registry and plugins
from .protocols import ProtocolRegistry
from .protocols.modbus import ModbusClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.SELECT, Platform.SWITCH]

async def async_install_frontend_resource(hass: HomeAssistant):
    """Ensure the frontend JS file is copied to the www/community folder."""
    
    def install():
        source_path = hass.config.path("custom_components", DOMAIN, "frontend", "protocol_wizard.js")
        target_dir = hass.config.path("www", "community", DOMAIN)
        target_path = os.path.join(target_dir, "protocol_wizard.js")

        try:
            if not os.path.exists(target_dir):
                _LOGGER.debug("Creating directory: %s", target_dir)
                os.makedirs(target_dir, exist_ok=True)

            if os.path.exists(source_path):
                shutil.copy2(source_path, target_path)
                _LOGGER.info("Updated frontend resource: %s", target_path)
            else:
                _LOGGER.warning("Frontend source file missing at %s", source_path)
                
        except Exception as err:
            _LOGGER.error("Failed to install frontend resource: %s", err)

    await hass.async_add_executor_job(install)

async def async_register_card(hass: HomeAssistant, entry: ConfigEntry):
    """Register the custom card as a Lovelace resource."""
    lovelace_data = hass.data.get("lovelace")
    if not lovelace_data:
        _LOGGER.debug("Unable to get lovelace data")
        return

    resources = lovelace_data.resources
    if not resources:
        _LOGGER.debug("Unable to get resources")
        return

    if not resources.loaded:
        await resources.async_load()

    card_url = f"/hacsfiles/{DOMAIN}/{DOMAIN}.js"

    for item in resources.async_items():
        if item["url"] == card_url:
            _LOGGER.debug("Card already registered: %s", card_url)
            return

    await resources.async_create_item({
        "res_type": "module",
        "url": card_url,
    })
    _LOGGER.debug("Card registered: %s", card_url)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Protocol Wizard from a config entry."""

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("connections", {})
    hass.data[DOMAIN].setdefault("coordinators", {})

    config = entry.data
    
# ----------------------------------------------------------------
    # Determine protocol correctly
    # ----------------------------------------------------------------
    # Explicit protocol wins (for future SNMP, BACnet, etc.)
    protocol_name = config.get(CONF_PROTOCOL)

    # Backward compatibility + Modbus detection
    if protocol_name is None:
        connection_type = config.get(CONF_CONNECTION_TYPE)
        if connection_type in (CONNECTION_TYPE_SERIAL, CONNECTION_TYPE_IP):
            protocol_name = CONF_PROTOCOL_MODBUS
        else:
            protocol_name = CONF_PROTOCOL_MODBUS  # safe fallback
    
    # Get protocol-specific coordinator class
    CoordinatorClass = ProtocolRegistry.get_coordinator_class(protocol_name)
    if not CoordinatorClass:
        _LOGGER.error("Unknown protocol: %s", protocol_name)
        return False
    
    # ----------------------------------------------------------------
    # Create protocol-specific client
    # ----------------------------------------------------------------
    try:
        if protocol_name == CONF_PROTOCOL_MODBUS:
            client = await _create_modbus_client(hass, config, entry)
        elif protocol_name == CONF_PROTOCOL_SNMP:
            client = _create_snmp_client(config)
        else:
            _LOGGER.error("Protocol %s not yet implemented", protocol_name)
            return False
    except Exception as err:
        _LOGGER.error("Failed to create client for %s: %s", protocol_name, err)
        return False
    
    # ----------------------------------------------------------------
    # Create coordinator
    # ----------------------------------------------------------------
    update_interval = entry.options.get(CONF_UPDATE_INTERVAL, 10)
    
    coordinator = CoordinatorClass(
        hass=hass,
        client=client,
        config_entry=entry,
        update_interval=timedelta(seconds=update_interval),
    )
    
    await coordinator.async_config_entry_first_refresh()
    
    hass.data[DOMAIN]["coordinators"][entry.entry_id] = coordinator
    
    # CREATE DEVICE REGISTRY ENTRY
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get(CONF_NAME, f"{protocol_name.title()} Device"),
        manufacturer=protocol_name.title(),
        model="Protocol Wizard",
        configuration_url=f"homeassistant://config/integrations/integration/{entry.entry_id}",
    )
    
    # ----------------------------------------------------------------
    # Platforms
    # ----------------------------------------------------------------
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # ----------------------------------------------------------------
    # Services (register once)
    # ----------------------------------------------------------------
    if not hass.data[DOMAIN].get("services_registered"):
        await async_setup_services(hass)
        hass.data[DOMAIN]["services_registered"] = True
    
    # ----------------------------------------------------------------
    # Frontend
    # ----------------------------------------------------------------
    await async_install_frontend_resource(hass)
    await async_register_card(hass, entry)
    
    return True


async def _create_modbus_client(hass: HomeAssistant, config: dict, entry: ConfigEntry) -> ModbusClient:
    """Create and cache Modbus client."""
    connection_type = config.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_SERIAL)
    protocol = config.get(CONF_PROTOCOL, CONNECTION_TYPE_TCP)
    
    # Create connection key for shared clients
    if connection_type == CONNECTION_TYPE_SERIAL:
        key = (
            f"serial:"
            f"{config[CONF_SERIAL_PORT]}:"
            f"{config.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)}:"
            f"{config.get(CONF_PARITY, DEFAULT_PARITY)}:"
            f"{config.get(CONF_STOPBITS, DEFAULT_STOPBITS)}:"
            f"{config.get(CONF_BYTESIZE, DEFAULT_BYTESIZE)}"
        )
        
        if key not in hass.data[DOMAIN]["connections"]:
            _LOGGER.debug("Creating serial Modbus client")
            hass.data[DOMAIN]["connections"][key] = AsyncModbusSerialClient(
                port=config[CONF_SERIAL_PORT],
                baudrate=config.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
                parity=config.get(CONF_PARITY, DEFAULT_PARITY),
                stopbits=config.get(CONF_STOPBITS, DEFAULT_STOPBITS),
                bytesize=config.get(CONF_BYTESIZE, DEFAULT_BYTESIZE),
                timeout=5,
            )
    elif connection_type == CONNECTION_TYPE_IP and protocol == CONNECTION_TYPE_UDP:
        key = f"ip_udp:{config[CONF_HOST]}:{config[CONF_PORT]}"
        
        if key not in hass.data[DOMAIN]["connections"]:
            _LOGGER.debug("Creating IP-UDP Modbus client")
            hass.data[DOMAIN]["connections"][key] = AsyncModbusUdpClient(
                host=config[CONF_HOST],
                port=config[CONF_PORT],
                timeout=5,
            )
    else:  # TCP
        key = f"ip_tcp:{config[CONF_HOST]}:{config[CONF_PORT]}"
        
        if key not in hass.data[DOMAIN]["connections"]:
            _LOGGER.debug("Creating IP-TCP Modbus client")
            hass.data[DOMAIN]["connections"][key] = AsyncModbusTcpClient(
                host=config[CONF_HOST],
                port=config[CONF_PORT],
                timeout=5,
            )
    
    pymodbus_client = hass.data[DOMAIN]["connections"][key]
    slave_id = int(config[CONF_SLAVE_ID])
    
    return ModbusClient(pymodbus_client, slave_id)

def _create_snmp_client(config: dict) -> SNMPClient:
    """Create SNMP client (no caching needed - connectionless)."""
    from .protocols.snmp import SNMPClient
    
    return SNMPClient(
        host=config[CONF_HOST],
        port=config.get(CONF_PORT, 161),
        community=config.get("community", "public"),
        version=config.get("version", "2c"),
    )

async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up protocol-agnostic services."""
    
    def _get_coordinator(call: ServiceCall):
        entity_id = None
        
        # Try to get entity_id from multiple sources (for compatibility)
        entity_id = None
        
        # 1. From service_data (when called via WS with entity_id in data)
        if "entity_id" in call.data:
            entity_ids = call.data["entity_id"]
            if isinstance(entity_ids, list):
                entity_id = entity_ids[0] if entity_ids else None
            else:
                entity_id = entity_ids
        
        # 2. From target (when called via UI with target selector)
        elif call.target and call.target.get("entity_id"):
            entity_ids = call.target.get("entity_id")
            entity_id = entity_ids[0] if isinstance(entity_ids, list) else entity_ids
        
        if not entity_id:
            raise HomeAssistantError("entity_id is required")
        
        from homeassistant.helpers import entity_registry as er
        ent_reg = er.async_get(hass)
        entity_entry = ent_reg.async_get(entity_id)
        
        entry_id = None
        if entity_entry and entity_entry.config_entry_id:
            entry_id = entity_entry.config_entry_id
        else:
            coordinators = hass.data.get(DOMAIN, {}).get("coordinators", {})
            if len(coordinators) == 1:
                entry_id = list(coordinators.keys())[0]
            elif len(coordinators) > 1:
                raise HomeAssistantError("Multiple coordinators found, cannot determine which to use")
            else:
                raise HomeAssistantError("No coordinators found")
        
        coordinator = hass.data[DOMAIN]["coordinators"].get(entry_id)
        if not coordinator:
            raise HomeAssistantError(f"Coordinator not found for entry {entry_id}")
        
        return coordinator
    
    async def handle_write_register(call: ServiceCall):
        """Generic write service (protocol-agnostic) with detailed logging."""
        coordinator = _get_coordinator(call)
    
        address = str(call.data["address"])
        value = call.data["value"]
        entity_config = {
            "data_type": call.data.get("data_type", "uint16"),
            "byte_order": call.data.get("byte_order", "big"),
            "word_order": call.data.get("word_order", "big"),
            "register_type": call.data.get("register_type", "holding"),
            "scale": call.data.get("scale", 1.0),
            "offset": call.data.get("offset", 0.0)
        }
    
   #     _LOGGER.debug("write_register service called: address=%s, value=%r (type=%s), config=%s", address, value, type(value).__name__, entity_config)
    
        try:
            success = await coordinator.async_write_entity(
                address=address,
                value=value,
                entity_config=entity_config,
                size=call.data.get("size"),
            )
    
            if not success:
                _LOGGER.error("Write failed for address %s with value %r – no specific error from coordinator", address, value)
                raise HomeAssistantError(f"Write failed for address {address}")
    
        except Exception as err:
            _LOGGER.error("Unexpected exception in write_register service for address %s: %s", address, err, exc_info=True)
            raise HomeAssistantError(f"Write failed for address {address}: {str(err)}") from err
    
    async def handle_read_register(call: ServiceCall):
        """Generic read service (protocol-agnostic)."""
        coordinator = _get_coordinator(call)
        
        entity_config = {
            "data_type": call.data.get("data_type", "uint16"),
            "byte_order": call.data.get("byte_order", "big"),
            "word_order": call.data.get("word_order", "big"),
            "register_type": call.data.get("register_type", "holding"),
            "scale": call.data.get("scale", 1.0),
            "offset": call.data.get("offset", 0.0)
        }
        
        value = await coordinator.async_read_entity(
            address=str(call.data["address"]),
            entity_config=entity_config,
            size=call.data.get("size", 1),
            raw=call.data.get("raw", False)
        )
        
        if value is None:
            raise HomeAssistantError(f"Failed to read address {call.data['address']}")
        
        return {"value": value}
    
    hass.services.async_register(DOMAIN, "write_register", handle_write_register)
    hass.services.async_register(
        DOMAIN,
        "read_register",
        handle_read_register,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "read_snmp",
        handle_read_snmp,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, "write_snmp", handle_write_snmp)
    
    async def handle_read_snmp(call: ServiceCall):
        """SNMP read service."""
        coordinator = _get_coordinator(call)
        
        oid = call.data.get("oid")
        if not oid:
            raise HomeAssistantError("oid is required")
        
        entity_config = {
            "data_type": call.data.get("data_type", "string"),
            "address": oid,  # SNMP uses OID as address
        }
        
        value = await coordinator.async_read_entity(
            address=oid,
            entity_config=entity_config,
        )
        
        if value is None:
            raise HomeAssistantError(f"Failed to read OID {oid}")
        
        return {"value": value}
    
    async def handle_write_snmp(call: ServiceCall):
        """SNMP write service."""
        coordinator = _get_coordinator(call)
        
        oid = call.data.get("oid")
        value = call.data.get("value")
        
        if not oid:
            raise HomeAssistantError("oid is required")
        if value is None:
            raise HomeAssistantError("value is required")
        
        entity_config = {
            "data_type": call.data.get("data_type", "string"),
            "address": oid,
        }
        
        _LOGGER.debug(
            "write_snmp service: oid=%s, value=%r, data_type=%s",
            oid, value, entity_config["data_type"]
        )
        
        success = await coordinator.async_write_entity(
            address=oid,
            value=value,
            entity_config=entity_config,
        )
        
        if not success:
            raise HomeAssistantError(f"Failed to write to OID {oid}")

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    
    coordinator = hass.data[DOMAIN]["coordinators"].pop(entry.entry_id, None)
    
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False
    
    # Close connection if unused
    if coordinator:
        client = coordinator.client
        still_used = any(
            c.client is client
            for c in hass.data[DOMAIN]["coordinators"].values()
        )
        
        if not still_used:
            try:
                await client.disconnect()
            except Exception as err:
                _LOGGER.debug("Error closing client: %s", err)
    
    return True
