#------------------------------------------
#-- base init.py protocol wizard
#------------------------------------------
"""The Protocol Wizard integration."""
import asyncio
import logging
import os
import re
import shutil
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.service import SupportsResponse
from pymodbus.client import (
    AsyncModbusSerialClient,
    AsyncModbusTcpClient,
    AsyncModbusUdpClient,
)

from .const import (
    CONF_BACNET_DEVICES,
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_CONNECTION_TYPE,
    CONF_ENTITIES,
    CONF_HOST,
    CONF_NAME,
    CONF_PARITY,
    CONF_PORT,
    CONF_PROTOCOL,
    CONF_PROTOCOL_BACNET,
    CONF_PROTOCOL_MODBUS,
    CONF_PROTOCOL_MQTT,
    CONF_PROTOCOL_SNMP,
    CONF_REGISTERS,
    CONF_SERIAL_PORT,
    CONF_SLAVE_ID,
    CONF_SLAVES,
    CONF_STOPBITS,
    CONF_TEMPLATE,
    CONF_TEMPLATE_APPLIED,
    CONF_UPDATE_INTERVAL,
    CONNECTION_TYPE_IP,
    CONNECTION_TYPE_SERIAL,
    CONNECTION_TYPE_TCP,
    CONNECTION_TYPE_UDP,
    DEFAULT_BAUDRATE,
    DEFAULT_BYTESIZE,
    DEFAULT_PARITY,
    DEFAULT_STOPBITS,
    DOMAIN,
    SIGNAL_ENTITY_SYNC,
)

# Import protocol registry and plugins
from .protocols import ProtocolRegistry
from .protocols.bacnet.client import BACnetClient
from .protocols.modbus import ModbusClient
from .protocols.mqtt import MQTTClient
from .protocols.snmp import SNMPClient
from .template_utils import ensure_user_template_dirs, load_template

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.SELECT, Platform.SWITCH]

# This integration can only be set up via config entries
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

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

        except OSError as err:
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


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Protocol Wizard integration (domain-level, runs once)."""
    # Initialize domain data storage
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("connections", {})
    hass.data[DOMAIN].setdefault("coordinators", {})
    hass.data[DOMAIN].setdefault("entry_coordinator_keys", {})
    hass.data[DOMAIN].setdefault("bus_locks", {})

    # Ensure template directories exist
    ensure_user_template_dirs(hass)

    # Register services (domain-level, shared across all entries)
    await async_setup_services(hass)

    # Install frontend resources (domain-level, shared across all entries)
    await async_install_frontend_resource(hass)
    # Note: Card registration needs an entry, so it's done in first entry setup

    _LOGGER.info("Protocol Wizard domain setup complete")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Protocol Wizard from a config entry."""
    # Domain data already initialized in async_setup()

    config = entry.data
    # Determine protocol
    protocol_name = config.get(CONF_PROTOCOL)
    if protocol_name is None:
        connection_type = config.get(CONF_CONNECTION_TYPE)
        if connection_type in (CONNECTION_TYPE_SERIAL, CONNECTION_TYPE_IP):
            protocol_name = CONF_PROTOCOL_MODBUS
        else:
            protocol_name = CONF_PROTOCOL_MODBUS

    # Get protocol-specific coordinator class
    CoordinatorClass = ProtocolRegistry.get_coordinator_class(protocol_name)
    if not CoordinatorClass:
        _LOGGER.error("Unknown protocol: %s", protocol_name)
        return False

    # Create protocol-specific client
    try:
        if protocol_name == CONF_PROTOCOL_MODBUS:
            # Get list of slaves (defaults to single slave from CONF_SLAVE_ID for backward compatibility)
            slaves = entry.options.get(CONF_SLAVES)

            _LOGGER.debug("[Modbus Setup] Entry: %s, has CONF_SLAVES: %s, count: %d",
                        entry.title, CONF_SLAVES in entry.options, len(slaves) if slaves else 0)

            if slaves is None:
                # Backward compatibility: CONF_SLAVES key doesn't exist = use CONF_SLAVE_ID and global CONF_REGISTERS
                default_slave_id = config.get(CONF_SLAVE_ID, 1)
                # Check if there are entities in the old location (backward compatibility)
                old_registers = entry.options.get(CONF_REGISTERS, [])

                # Check if there's a pending template from config_flow
                pending_template = entry.options.get(CONF_TEMPLATE)

                _LOGGER.info("[Modbus Setup] Migrating: slave_id=%d, %d entities, template=%s",
                             default_slave_id, len(old_registers), pending_template or "None")

                # Build slave structure
                slave_data = {
                    "slave_id": default_slave_id,
                    "name": entry.title or "Primary",
                    "registers": old_registers  # Migrate old entities to slave AS-IS
                }

                # Copy pending template to slave so it gets loaded
                if pending_template:
                    slave_data["template"] = pending_template
                    _LOGGER.info("Migrating template '%s' to slave structure", pending_template)

                slaves = [slave_data]

                # Save the migration to options so it persists
                options = dict(entry.options)
                options[CONF_SLAVES] = slaves
                # Remove old CONF_REGISTERS and CONF_TEMPLATE (moved to slave)
                options.pop(CONF_REGISTERS, None)
                options.pop(CONF_TEMPLATE, None)
                hass.config_entries.async_update_entry(entry, options=options)
                _LOGGER.info("[Modbus Setup] Migration complete")
            elif not slaves:
                # CONF_SLAVES exists but is empty - this shouldn't happen but handle gracefully
                _LOGGER.warning("[Modbus Setup] CONF_SLAVES exists but is empty - no slaves to set up")
                return True  # Setup "succeeded" but nothing to do
            else:
                _LOGGER.debug("[Modbus Setup] Using existing slaves: %d slaves", len(slaves))

            # Create a shared bus lock for this connection
            bus_lock_key = _get_bus_lock_key(config)
            if bus_lock_key not in hass.data[DOMAIN]["bus_locks"]:
                hass.data[DOMAIN]["bus_locks"][bus_lock_key] = asyncio.Lock()
            shared_lock = hass.data[DOMAIN]["bus_locks"][bus_lock_key]

            # Create a coordinator for each slave
            coordinators_created = []
            for idx, slave_info in enumerate(slaves):
                slave_id = slave_info["slave_id"]
                slave_name = slave_info.get("name", f"Slave {slave_id}")

                _LOGGER.info("[Modbus Setup] Creating coordinator for slave %d (%s), %d entities",
                            slave_id, slave_name, len(slave_info.get('registers', [])))

                # Override slave_id in config for this slave
                slave_config = dict(config)
                slave_config[CONF_SLAVE_ID] = slave_id

                # Create client (uses shared connection via existing caching)
                client = await _create_modbus_client(hass, slave_config, entry)
                _LOGGER.debug("[Modbus Setup] Created client for slave %d, client.slave_id=%d",
                             slave_id, client.slave_id)

                # Create coordinator with slave-specific entity list
                update_interval = entry.options.get(CONF_UPDATE_INTERVAL, 10)

                coordinator = CoordinatorClass(
                    hass=hass,
                    client=client,
                    config_entry=entry,
                    update_interval=timedelta(seconds=update_interval),
                )

                # Store slave_id in coordinator so it knows which entities to read
                coordinator.slave_id = slave_id
                coordinator.slave_index = idx  # Index in slaves list
                # Inject shared bus lock for cross-slave safety
                coordinator._lock = shared_lock

                # Load template for this specific slave if specified
                slave_template = slave_info.get("template")
                current_register_count = len(slave_info.get("registers", []))
                _LOGGER.debug("[Modbus Setup] Slave %d: template=%s, template_applied=%s, current_registers=%d",
                             slave_id, slave_template, slave_info.get("template_applied"), current_register_count)

                if slave_template and not slave_info.get("template_applied"):
                    _LOGGER.info("Loading template '%s' for slave %d (%s)", slave_template, slave_id, slave_name)
                    template_entities = await load_template(hass, protocol_name, slave_template)
                    if template_entities:
                        slave_info["registers"] = template_entities
                        slave_info["template_applied"] = True
                        _LOGGER.info("[Modbus Setup] Loaded %d entities from template for slave %d",
                                    len(template_entities), slave_id)

                        # Save back to options
                        options = dict(entry.options)
                        options[CONF_SLAVES] = slaves
                        hass.config_entries.async_update_entry(entry, options=options)
                        _LOGGER.debug("[Modbus Setup] Saved template entities to options for slave %d", slave_id)
                    else:
                        _LOGGER.warning("[Modbus Setup] Template '%s' returned no entities for slave %d",
                                       slave_template, slave_id)
                elif slave_template and slave_info.get("template_applied"):
                    _LOGGER.debug("[Modbus Setup] Slave %d: template already applied, using %d existing entities",
                                 slave_id, current_register_count)

                await coordinator.async_config_entry_first_refresh()

                # Always use consistent coordinator_key format
                coordinator_key = f"{entry.entry_id}_slave_{slave_id}"

                # Store coordinator_key in coordinator for device identification
                coordinator.coordinator_key = coordinator_key

                hass.data[DOMAIN]["coordinators"][coordinator_key] = coordinator

                # BACKWARD COMPAT: Also store first slave with entry.entry_id for platform access
                if idx == 0:
                    hass.data[DOMAIN]["coordinators"][entry.entry_id] = coordinator

                coordinators_created.append((coordinator_key, slave_name, slave_id))

            # Store coordinator keys for this entry (for platform access)
            hass.data[DOMAIN]["entry_coordinator_keys"][entry.entry_id] = [
                key for key, _, _ in coordinators_created
            ]

            # Create device registry entries for each slave
            device_registry = dr.async_get(hass)
            for coordinator_key, slave_name, slave_id in coordinators_created:
                hub_name = entry.title or entry.data.get(CONF_NAME) or f"{protocol_name.title()} Device"
                # Always include slave name for clarity (even for single slave)
                devicename = f"{hub_name} - {slave_name}"

                # Check if device already exists (may need name update after adding slaves)
                existing_device = device_registry.async_get_device(identifiers={(DOMAIN, coordinator_key)})
                if existing_device:
                    # Update name if it changed (e.g., was "Hub" now should be "Hub - Slave 1")
                    if existing_device.name != devicename:
                        device_registry.async_update_device(existing_device.id, name=devicename)
                else:
                    device_registry.async_get_or_create(
                        config_entry_id=entry.entry_id,
                        identifiers={(DOMAIN, coordinator_key)},
                        name=devicename,
                        manufacturer=protocol_name.title(),
                        model=f"Protocol Wizard (Slave {slave_id})",
                        configuration_url=f"homeassistant://config/integrations/integration/{entry.entry_id}",
                    )

            # Platforms (forward to all platforms once for all slaves)
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        elif protocol_name == CONF_PROTOCOL_BACNET:
            # BACnet handling
            bacnet_devices = entry.options.get(CONF_BACNET_DEVICES, [])

            _LOGGER.info("[BACnet Setup] Entry: %s, has %d devices",
                        entry.title, len(bacnet_devices))

            _LOGGER.debug("[BACnet Setup] Full bacnet_devices structure: %s", bacnet_devices)

            if not bacnet_devices:
                _LOGGER.warning("No BACnet devices configured - skipping")
                return False

            # For now, only support first device
            device_info = bacnet_devices[0]
            device_id = device_info["device_id"]
            device_name = device_info.get("name", f"BACnet Device {device_id}")
            device_address = device_info["address"]

            _LOGGER.info("[BACnet Setup] Creating client for device %d (%s) at %s, %d entities",
                        device_id, device_name, device_address, len(device_info.get('entities', [])))

            bacnet_client = BACnetClient(
                hass=hass,
                host=device_address,
                device_id=device_id,
                port=device_info.get("port", 47808),
                network_number=config.get("network_number")
            )

            try:
                if not await bacnet_client.connect():
                    _LOGGER.error("Failed to connect to BACnet device %d at %s", device_id, device_address)
                    return False
            except OSError as err:
                if err.errno == 98:  # Address already in use
                    _LOGGER.error("Port 47808 is already in use! Restart Home Assistant to clear all BACnet connections")
                    return False
                raise

            from .protocols.bacnet.coordinator import BACnetCoordinator

            update_interval = entry.options.get(CONF_UPDATE_INTERVAL, 10)

            coordinator = BACnetCoordinator(
                hass=hass,
                client=bacnet_client,
                config_entry=entry,
                update_interval=timedelta(seconds=update_interval),
            )

            # Store device index for entity lookup (always 0 for single device)
            coordinator.device_index = 0

            # Handle template loading
            template_name = device_info.get("template")
            if template_name and not device_info.get("template_applied"):
                _LOGGER.info("Loading template '%s' for BACnet device %d", template_name, device_id)
                template_entities = await load_template(hass, CONF_PROTOCOL_BACNET, template_name)
                if template_entities:
                    device_info["entities"] = template_entities
                    device_info["template_applied"] = True

                    # Save back to options
                    options = dict(entry.options)
                    options[CONF_BACNET_DEVICES] = bacnet_devices
                    hass.config_entries.async_update_entry(entry, options=options)

            await coordinator.async_config_entry_first_refresh()

            hass.data[DOMAIN]["coordinators"][entry.entry_id] = coordinator
            hass.data[DOMAIN]["entry_coordinator_keys"][entry.entry_id] = [entry.entry_id]

            devicename = entry.title or entry.data.get(CONF_NAME) or "BACnet Device"

            device_registry = dr.async_get(hass)
            device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, entry.entry_id)},
                name=devicename,
                manufacturer="BACnet",
                model=f"BACnet Device {device_id}",
                configuration_url=f"homeassistant://config/integrations/integration/{entry.entry_id}",
            )

            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        elif protocol_name == CONF_PROTOCOL_SNMP:
            client = _create_snmp_client(config)
        elif protocol_name == CONF_PROTOCOL_MQTT:
            client = _create_mqtt_client(config)
        else:
            _LOGGER.error("Protocol %s not yet implemented", protocol_name)
            return False
    except (OSError, ConnectionError, TimeoutError, ValueError) as err:
        _LOGGER.error("Failed to create client for %s: %s", protocol_name, err)
        return False

    # For non-Modbus, non-BACnet protocols, create single coordinator
    if protocol_name not in (CONF_PROTOCOL_MODBUS, CONF_PROTOCOL_BACNET):
        # Create coordinator
        update_interval = entry.options.get(CONF_UPDATE_INTERVAL, 10)

        coordinator = CoordinatorClass(
            hass=hass,
            client=client,
            config_entry=entry,
            update_interval=timedelta(seconds=update_interval),
        )

        template_name = entry.options.get(CONF_TEMPLATE)

        if (template_name and not entry.options.get(CONF_TEMPLATE_APPLIED)):
            _LOGGER.info("Loading template '%s' for new device", template_name)
            await _load_template_into_options(hass, entry, protocol_name, template_name)

            # mark as applied - but reload entry first to get the updated options!
            entry = hass.config_entries.async_get_entry(entry.entry_id)
            options = dict(entry.options)
            options[CONF_TEMPLATE_APPLIED] = True
            hass.config_entries.async_update_entry(entry, options=options)


        await coordinator.async_config_entry_first_refresh()

        hass.data[DOMAIN]["coordinators"][entry.entry_id] = coordinator
        hass.data[DOMAIN]["entry_coordinator_keys"][entry.entry_id] = [entry.entry_id]

        devicename = entry.title or entry.data.get(CONF_NAME) or f"{protocol_name.title()} Device"

        # CREATE DEVICE REGISTRY ENTRY
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.entry_id)},
            name=devicename,
            manufacturer=protocol_name.title(),
            model="Protocol Wizard",
            configuration_url=f"homeassistant://config/integrations/integration/{entry.entry_id}",
        )

        # Platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register Lovelace card (needs entry parameter, so done here on first entry)
    if not hass.data[DOMAIN].get("card_registered"):
        await async_register_card(hass, entry)
        hass.data[DOMAIN]["card_registered"] = True

    return True


def _get_bus_lock_key(config: dict) -> str:
    """Get a unique key for the physical bus connection."""
    connection_type = config.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_SERIAL)
    if connection_type == CONNECTION_TYPE_SERIAL:
        return f"serial:{config.get(CONF_SERIAL_PORT, 'unknown')}"
    return f"ip:{config.get(CONF_HOST, 'unknown')}:{config.get(CONF_PORT, 502)}"


async def _load_template_into_options(
    hass: HomeAssistant,
    entry: ConfigEntry,
    protocol: str,
    template_name: str,
) -> None:
    """Load template entities into entry options."""

    try:

        template_data = await load_template(hass, protocol, template_name)

        if not template_data:
            _LOGGER.warning("Template %s is empty", template_name)
            return

        # Update options with template entities
        new_options = dict(entry.options)

        if protocol == CONF_PROTOCOL_MODBUS:
            # For Modbus, check if we have slave structure
            slaves = new_options.get(CONF_SLAVES, [])
            if slaves:
                # Put entities into first slave's registers
                slaves[0]["registers"] = template_data
                new_options[CONF_SLAVES] = slaves
                _LOGGER.info("Loaded %d entities from template '%s' into slave %d",
                            len(template_data), template_name, slaves[0]["slave_id"])
            else:
                # Fallback to old structure (shouldn't happen after migration)
                new_options[CONF_REGISTERS] = template_data
                _LOGGER.info("Loaded %d entities from template '%s' (old structure)", len(template_data), template_name)
        elif protocol == CONF_PROTOCOL_BACNET:
            # For BACnet, check if we have device structure
            bacnet_devices = new_options.get(CONF_BACNET_DEVICES, [])
            if bacnet_devices:
                bacnet_devices[0]["entities"] = template_data
                new_options[CONF_BACNET_DEVICES] = bacnet_devices
                _LOGGER.info("Loaded %d entities from template '%s' into BACnet device %d",
                            len(template_data), template_name, bacnet_devices[0]["device_id"])
            else:
                # Fallback to old structure
                new_options[CONF_ENTITIES] = template_data
                _LOGGER.info("Loaded %d entities from template '%s' (old structure)", len(template_data), template_name)
        else:
            # Other protocols (SNMP, MQTT, etc.) use CONF_ENTITIES
            new_options[CONF_ENTITIES] = template_data
            _LOGGER.info("Loaded %d entities from template '%s'", len(template_data), template_name)

        hass.config_entries.async_update_entry(entry, options=new_options)

    except (OSError, KeyError, TypeError, ValueError) as err:
        _LOGGER.error("Failed to load template %s: %s", template_name, err)


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
                timeout=3,
                retries=1,  # Reduce from default 3 to speed up failure detection
            )
    elif connection_type == CONNECTION_TYPE_IP and protocol == CONNECTION_TYPE_UDP:
        key = f"ip_udp:{config[CONF_HOST]}:{config[CONF_PORT]}"

        if key not in hass.data[DOMAIN]["connections"]:
            _LOGGER.debug("Creating IP-UDP Modbus client")
            hass.data[DOMAIN]["connections"][key] = AsyncModbusUdpClient(
                host=config[CONF_HOST],
                port=config[CONF_PORT],
                timeout=3,
                retries=1,  # Reduce from default 3 to speed up failure detection
            )
    else:  # TCP
        key = f"ip_tcp:{config[CONF_HOST]}:{config[CONF_PORT]}"

        if key not in hass.data[DOMAIN]["connections"]:
            _LOGGER.debug("Creating IP-TCP Modbus client")
            hass.data[DOMAIN]["connections"][key] = AsyncModbusTcpClient(
                host=config[CONF_HOST],
                port=config[CONF_PORT],
                timeout=3,
                retries=1,  # Reduce from default 3 to speed up failure detection
            )

    pymodbus_client = hass.data[DOMAIN]["connections"][key]
    slave_id = int(config[CONF_SLAVE_ID])

    _LOGGER.debug("[Modbus] Creating ModbusClient wrapper for slave_id=%d (pymodbus_client id=%d)",
                 slave_id, id(pymodbus_client))
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

def _create_mqtt_client(config: dict) -> MQTTClient:
    """Create MQTT client (no caching needed - manages its own connection)."""
    from .protocols.mqtt import (
        CONF_BROKER,
        CONF_PASSWORD,
        CONF_USERNAME,
        DEFAULT_PORT,
        MQTTClient,
    )

    return MQTTClient(
        broker=config[CONF_BROKER],
        port=config.get(CONF_PORT, DEFAULT_PORT),
        username=config.get(CONF_USERNAME) or None,
        password=config.get(CONF_PASSWORD) or None,
        timeout=10.0,
    )

def _create_bacnet_client(config: dict, hass: HomeAssistant) -> BACnetClient:
    """Create BACnet client (no caching needed - connectionless)."""
    return BACnetClient(
        host=config[CONF_HOST],
        hass = hass,
        device_id=config["device_id"],
        port=config.get(CONF_PORT, 47808),
        network_number=config.get("network_number")
    )

async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up protocol-agnostic services."""

    def _get_coordinator(call: ServiceCall):
        """Find the right coordinator for a service call."""
        # Priority 1: device_id from service data (sent by card)
        device_id = call.data.get("device_id")
        if device_id:
            dev_reg = dr.async_get(hass)
            device = dev_reg.async_get(device_id)
            if device:
                # Check device identifiers against known coordinator keys
                for identifier in device.identifiers:
                    if identifier[0] == DOMAIN:
                        coordinator_key = identifier[1]
                        coordinator = hass.data[DOMAIN]["coordinators"].get(coordinator_key)
                        if coordinator:
                            _LOGGER.debug("Coordinator selected by device_id %s: protocol=%s, key=%s",
                                          device_id, coordinator.protocol_name, coordinator_key)
                            return coordinator

                # Fallback: check config entries
                for entry_id in device.config_entries:
                    coordinator = hass.data[DOMAIN]["coordinators"].get(entry_id)
                    if coordinator:
                        _LOGGER.debug("Coordinator selected by device_id %s (entry fallback): protocol=%s, entry=%s",
                                      device_id, coordinator.protocol_name, entry_id)
                        return coordinator
                raise HomeAssistantError(f"No active coordinator found for device {device_id}")

        # Priority 2: Fallback to entity_id (for legacy/UI calls without device_id)
        entity_id = None
        if "entity_id" in call.data:
            entity_ids = call.data["entity_id"]
            entity_id = entity_ids[0] if isinstance(entity_ids, list) else entity_ids
        elif call.target and call.target.get("entity_id"):
            entity_ids = call.target.get("entity_id")
            entity_id = entity_ids[0] if isinstance(entity_ids, list) else entity_ids

        if entity_id:
            from homeassistant.helpers import entity_registry as er
            ent_reg = er.async_get(hass)
            entity_entry = ent_reg.async_get(entity_id)
            if entity_entry and entity_entry.config_entry_id:
                entry_id = entity_entry.config_entry_id
                # Try to find coordinator by the entity's device
                if entity_entry.device_id:
                    dev_reg = dr.async_get(hass)
                    device = dev_reg.async_get(entity_entry.device_id)
                    if device:
                        for identifier in device.identifiers:
                            if identifier[0] == DOMAIN:
                                coordinator = hass.data[DOMAIN]["coordinators"].get(identifier[1])
                                if coordinator:
                                    return coordinator
                # Fallback to entry_id
                coordinator = hass.data[DOMAIN]["coordinators"].get(entry_id)
                if coordinator:
                    _LOGGER.debug("Coordinator selected by entity_id %s: protocol=%s", entity_id, coordinator.protocol_name)
                    return coordinator

        raise HomeAssistantError("No coordinator found – provide device_id or valid entity_id")

    async def handle_add_entity(call: ServiceCall):
        """Service to add a new entity to the integration configuration."""
        try:
            # Get the config entry from target entity
            entry_id = None

            # Get entity_id from target or from data (for frontend card compatibility)
            entity_id = call.data.get("entity_id")

            if not entity_id and call.target:
                entity_ids = call.target.get("entity_id")
                if entity_ids:
                    entity_id = entity_ids[0] if isinstance(entity_ids, list) else entity_ids

            if not entity_id:
                raise HomeAssistantError("No target entity provided")

            # Get config entry from entity
            entity_registry = er.async_get(hass)
            entity_entry = entity_registry.async_get(entity_id)
            if entity_entry and entity_entry.config_entry_id:
                entry_id = entity_entry.config_entry_id

            if not entry_id:
                raise HomeAssistantError("Could not find config entry for target entity")

            entry = hass.config_entries.async_get_entry(entry_id)
            if not entry or entry.domain != DOMAIN:
                raise HomeAssistantError("Invalid config entry")

            # Determine protocol and config key
            protocol = entry.data.get(CONF_PROTOCOL, CONF_PROTOCOL_MODBUS)

            # Get current entities based on protocol and structure
            current_options = dict(entry.options)

            # Support slave_id parameter for multi-slave Modbus
            target_slave_id = call.data.get("slave_id")

            # If slave_id not provided, try to extract from hub entity's unique_id or entity_id
            # Hub entity unique_id format: {entry_id}_slave_{slave_id}_{protocol}_hub
            # Hub entity_id format: sensor.slave_{slave_id}_{protocol}_hub
            if target_slave_id is None and entity_entry:
                # Try unique_id first (more reliable)
                if entity_entry.unique_id:
                    match = re.search(r'_slave_(\d+)_', entity_entry.unique_id)
                    if match:
                        target_slave_id = int(match.group(1))
                        _LOGGER.debug("Extracted slave_id %d from unique_id: %s",
                                     target_slave_id, entity_entry.unique_id)
                # Fallback to entity_id pattern
                if target_slave_id is None and entity_id:
                    match = re.search(r'slave_(\d+)_', entity_id)
                    if match:
                        target_slave_id = int(match.group(1))
                        _LOGGER.debug("Extracted slave_id %d from entity_id: %s",
                                     target_slave_id, entity_id)

            if protocol == CONF_PROTOCOL_MODBUS:
                # Check if we have slaves (new structure)
                slaves = current_options.get(CONF_SLAVES, [])
                if slaves:
                    # Find the target slave
                    slave_idx = 0
                    if target_slave_id is not None:
                        target_slave_id = int(target_slave_id)
                        for i, s in enumerate(slaves):
                            if s.get("slave_id") == target_slave_id:
                                slave_idx = i
                                break
                        else:
                            # Slave ID from entity not found in slaves list - log warning and use first slave
                            _LOGGER.warning("Slave ID %d not found in slaves list, using first slave",
                                          target_slave_id)
                            slave_idx = 0
                    entities = list(slaves[slave_idx].get("registers", []))
                else:
                    # Old structure fallback
                    entities = list(current_options.get(CONF_REGISTERS, []))
            else:
                # Non-Modbus protocols
                entities = list(current_options.get(CONF_ENTITIES, []))

            # Build new entity config
            new_entity = {
                "name": call.data["name"],
                "address": str(call.data["address"]),
                "data_type": call.data.get("data_type", "uint16"),
                "rw": call.data.get("rw", "read"),
                "scale": float(call.data.get("scale", 1.0)),
                "offset": float(call.data.get("offset", 0.0)),
            }

            # Add protocol-specific fields
            if protocol == CONF_PROTOCOL_MODBUS:
                new_entity.update({
                    "register_type": call.data.get("register_type", "holding"),
                    "byte_order": call.data.get("byte_order", "big"),
                    "word_order": call.data.get("word_order", "big"),
                    "size": int(call.data.get("size", 1)),
                })
            elif protocol == CONF_PROTOCOL_SNMP:
                new_entity.update({
                    "read_mode": call.data.get("read_mode", "get"),
                })

            # Add optional fields if provided
            for field in ["format", "options", "device_class", "state_class", "entity_category", "icon", "min", "max", "step"]:
                if call.data.get(field):
                    new_entity[field] = call.data[field]

            # Check for duplicates
            existing_addresses = {(e.get("name"), e.get("address")) for e in entities}
            if (new_entity["name"], new_entity["address"]) in existing_addresses:
                raise HomeAssistantError(f"Entity with name '{new_entity['name']}' and address '{new_entity['address']}' already exists")

            # Add the new entity
            entities.append(new_entity)

            # Save back to correct location
            if protocol == CONF_PROTOCOL_MODBUS:
                slaves = current_options.get(CONF_SLAVES, [])
                if slaves:
                    slave_idx = 0
                    if target_slave_id is not None:
                        for i, s in enumerate(slaves):
                            if s.get("slave_id") == int(target_slave_id):
                                slave_idx = i
                                break
                    slaves[slave_idx]["registers"] = entities
                    current_options[CONF_SLAVES] = slaves
                else:
                    # Old structure fallback
                    current_options[CONF_REGISTERS] = entities
            else:
                # Non-Modbus protocols
                current_options[CONF_ENTITIES] = entities

            # Update the config entry
            hass.config_entries.async_update_entry(entry, options=current_options)

            # Notify entity managers to sync (since update_listener is only triggered by options flow)
            async_dispatcher_send(hass, f"{SIGNAL_ENTITY_SYNC}_{entry.entry_id}")
            _LOGGER.debug("Dispatched entity sync signal for entry %s", entry.entry_id)

            # Trigger coordinator refresh so new entity gets data immediately
            if target_slave_id is not None:
                coordinator_key = f"{entry.entry_id}_slave_{target_slave_id}"
            else:
                coordinator_key = entry.entry_id
            coordinator = hass.data[DOMAIN]["coordinators"].get(coordinator_key)
            if coordinator:
                await coordinator.async_request_refresh()
                _LOGGER.debug("Triggered coordinator refresh for %s", coordinator_key)

            # Include slave info in log for multi-slave debugging
            slave_info_str = f" (slave {target_slave_id})" if target_slave_id is not None else ""
            _LOGGER.info(
                "Added new entity '%s' at address '%s' to %s%s",
                new_entity["name"],
                new_entity["address"],
                entry.title,
                slave_info_str
            )

            return {
                "success": True,
                "entity_name": new_entity["name"],
                "entity_count": len(entities)
            }

        except Exception as err:
            _LOGGER.exception("Failed to add entity")
            raise HomeAssistantError(f"Failed to add entity: {err!s}") from err

    async def handle_write_register(call: ServiceCall):
        """Generic write service (protocol-agnostic) with detailed logging."""
        coordinator = _get_coordinator(call)

        address = str(call.data["address"])
        value = call.data["value"]
        entity_config = {
            "data_type": call.data.get("data_type", "uint16"),
            "device_id": call.data.get("device_id", None),
            "byte_order": call.data.get("byte_order", "big"),
            "word_order": call.data.get("word_order", "big"),
            "register_type": call.data.get("register_type", "holding"),
            "scale": call.data.get("scale", 1.0),
            "offset": call.data.get("offset", 0.0)
        }

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
            _LOGGER.exception("Unexpected exception in write_register service for address %s", address)
            raise HomeAssistantError(f"Write failed for address {address}: {err!s}") from err

    async def handle_read_register(call: ServiceCall):
        """Generic read service (protocol-agnostic)."""
        coordinator = _get_coordinator(call)

        entity_config = {
            "data_type": call.data.get("data_type", "uint16"),
            "device_id": call.data.get("device_id", None),
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

    async def handle_read_snmp(call: ServiceCall):
        """SNMP read service."""
        coordinator = _get_coordinator(call)

        oid = call.data.get("oid")
        if not oid:
            raise HomeAssistantError("oid is required")

        entity_config = {
            "data_type": call.data.get("data_type", "string"),
            "device_id": call.data.get("device_id", None),
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
            "device_id": call.data.get("device_id", None),
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

    async def handle_read_mqtt(call: ServiceCall):
        """MQTT read service."""
        coordinator = _get_coordinator(call)

        topic = call.data["topic"]
        wait_time = call.data.get("wait_time", 5.0)

        entity_config = {
            "data_type": "string",  # Default to string
        }

        value = await coordinator.async_read_entity(
            address=topic,
            entity_config=entity_config,
            wait_time=wait_time,
        )

        if value is None:
            raise HomeAssistantError(f"Failed to read MQTT topic {topic} (timeout or no data)")

        return {"value": value}

    async def handle_write_mqtt(call: ServiceCall):
        """MQTT write/publish service."""
        coordinator = _get_coordinator(call)

        topic = call.data["topic"]
        payload = call.data["payload"]
        qos = int(call.data.get("qos", 0))
        retain = call.data.get("retain", False)

        entity_config = {
            "data_type": "string",
        }

        success = await coordinator.async_write_entity(
            address=topic,
            value=payload,
            entity_config=entity_config,
            qos=qos,
            retain=retain,
        )

        if not success:
            raise HomeAssistantError(f"Failed to publish to MQTT topic {topic}")

        return {"success": True}

    async def handle_read_bacnet(call: ServiceCall):
        """BACnet read service."""
        coordinator = _get_coordinator(call)

        address = call.data.get("address")
        device_instance = call.data.get("device_instance")
        if not address:
            raise HomeAssistantError("address is required for bacnet read")

        entity_config = {
            "address": address,
            "data_type": call.data.get("data_type", "float"),
            "device_id": call.data.get("device_id", None),
            "device_instance" : device_instance
        }
        value = None
        try:
            value = await coordinator.async_read_entity(
                address=address,
                entity_config=entity_config,
            )
        except (OSError, ConnectionError, TimeoutError) as err:
            _LOGGER.debug("BACnet Read failed with error: %s", err)
        if value is None:
            raise HomeAssistantError(f"Failed to read BACnet address {address}")

        return {"value": value}

    async def handle_write_bacnet(call: ServiceCall):
        """BACnet write service."""
        coordinator = _get_coordinator(call)

        address = call.data.get("address")
        value = call.data.get("value")
        device_instance = call.data.get("device_instance")

        if not address:
            raise HomeAssistantError("address is required for bacnet write")
        if value is None:
            raise HomeAssistantError("value is required for bacnet write")

        entity_config = {
            "address": address,
            "data_type": call.data.get("data_type", "float"),
            "device_id": call.data.get("device_id", None),
            "priority": call.data.get("priority", 8),  # BACnet write priority
            "device_instance" : device_instance
        }

        _LOGGER.debug(
            "write_bacnet service: address=%s, value=%r, priority=%s",
            address, value, entity_config.get("priority")
        )
        success = False
        try:
            success = await coordinator.async_write_entity(
                address=address,
                value=value,
                entity_config=entity_config,
            )
        except (OSError, ConnectionError, TimeoutError) as err:
            _LOGGER.debug("BACnet write failed with error: %s", err)

        if not success:
            raise HomeAssistantError(f"Failed to write to BACnet address {address}")

        return {"success": True}

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
    hass.services.async_register(
        DOMAIN,
        "add_entity",
        handle_add_entity,
    )
    hass.services.async_register(
        DOMAIN,
        "read_mqtt",
        handle_read_mqtt,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "write_mqtt",
        handle_write_mqtt,
    )
    hass.services.async_register(
        DOMAIN,
        "read_bacnet",
        handle_read_bacnet,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "write_bacnet",
        handle_write_bacnet,
    )

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    protocol = entry.data.get(CONF_PROTOCOL)

    # Clean up entry_coordinator_keys
    hass.data[DOMAIN].get("entry_coordinator_keys", {}).pop(entry.entry_id, None)

    # For Modbus multi-slave, clean up all coordinators
    if protocol == CONF_PROTOCOL_MODBUS:
        # Clean up Modbus multi-slave coordinators
        coordinators_to_remove = [
            key for key in hass.data[DOMAIN]["coordinators"]
            if key.startswith(f"{entry.entry_id}_slave_")
        ]

        for coord_key in coordinators_to_remove:
            hass.data[DOMAIN]["coordinators"].pop(coord_key, None)

        # Also remove backward-compat entry
        coordinator = hass.data[DOMAIN]["coordinators"].pop(entry.entry_id, None)

        # Close Modbus client if unused
        if coordinator:
            client = coordinator.client
            still_used = any(
                c.client is client
                for c in hass.data[DOMAIN]["coordinators"].values()
            )

            if not still_used:
                try:
                    await client.disconnect()
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Error closing Modbus client: %s", err)
    else:
        # Other protocols (SNMP, MQTT, etc.)
        coordinator = hass.data[DOMAIN]["coordinators"].pop(entry.entry_id, None)

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
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Error closing client: %s", err)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    # Clean up entity managers and their signal subscriptions
    if "entity_managers" in hass.data[DOMAIN]:
        managers = hass.data[DOMAIN]["entity_managers"].pop(entry.entry_id, [])
        for manager in managers:
            if hasattr(manager, '_unsub_dispatcher') and manager._unsub_dispatcher:
                manager._unsub_dispatcher()
        _LOGGER.debug("Cleaned up %d entity managers for entry %s", len(managers), entry.entry_id)

    return True
