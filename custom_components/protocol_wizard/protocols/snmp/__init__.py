#------------------------------------------
#-- protocol snmp init.py protocol wizard
#------------------------------------------

"""SNMP protocol plugin."""
from .client import SNMPClient
from .const import CONF_ENTITIES, SNMP_DATA_TYPES, oid_key
from .coordinator import SNMPCoordinator

__all__ = ["CONF_ENTITIES", "SNMP_DATA_TYPES", "SNMPClient", "SNMPCoordinator", "oid_key"]
