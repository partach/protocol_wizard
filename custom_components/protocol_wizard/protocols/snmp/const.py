#------------------------------------------
#-- protocol snmp const.py protocol wizard
#------------------------------------------
"""SNMP-specific constants."""

# Config key for SNMP entities (uses standard "entities" not "registers")
CONF_ENTITIES = "entities"

# SNMP data type mapping - no fixed sizes like Modbus
# SNMP types are dynamic based on MIB definitions
SNMP_DATA_TYPES = [
    "string",
    "integer",
    "counter32",
    "counter64",
    "gauge32",
    "timeticks",
    "ipaddress",
    "objectid",
]

# SNMP versions
SNMP_VERSIONS = {
    "1": 0,   # SNMPv1
    "2c": 1,  # SNMPv2c
    "3": 3,   # SNMPv3
}

def oid_key(name: str) -> str:
    """Generate consistent key from OID name."""
    return name.lower().strip().replace(" ", "_")
