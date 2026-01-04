#------------------------------------------
#-- protocol snmp init.py protocol wizard
#------------------------------------------

"""SNMP protocol plugin."""
from .coordinator import SNMPCoordinator
from .client import SNMPClient
from .const import CONF_ENTITIES, SNMP_DATA_TYPES, oid_key

__all__ = ["SNMPCoordinator", "SNMPClient", "CONF_ENTITIES", "SNMP_DATA_TYPES", "oid_key"]
