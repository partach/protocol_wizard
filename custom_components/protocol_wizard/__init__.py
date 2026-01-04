#------------------------------------------
#-- base init.py protocol wizard
#------------------------------------------
# __init__.py

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Protocol Wizard from config entry."""
    
    protocol_name = entry.data["protocol"]
    
    # Get protocol-specific coordinator class
    CoordinatorClass = ProtocolRegistry.get_coordinator_class(protocol_name)
    if not CoordinatorClass:
        raise ValueError(f"Unknown protocol: {protocol_name}")
    
    # Create protocol-specific client
    if protocol_name == "modbus":
        client = create_modbus_client(entry.data)
    elif protocol_name == "snmp":
        client = SNMPClient(
            host=entry.data["host"],
            community=entry.data["community"],
            version=entry.data["version"]
        )
    
    # Create coordinator
    coordinator = CoordinatorClass(
        hass=hass,
        client=client,
        config_entry=entry,
        update_interval=timedelta(seconds=entry.options.get(CONF_UPDATE_INTERVAL, 30))
    )
    
    await coordinator.async_config_entry_first_refresh()
    
    # Store coordinator
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    
    # Forward to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True
