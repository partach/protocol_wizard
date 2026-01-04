#------------------------------------------
#-- protocol modbus const.py protocol wizard
#------------------------------------------
"""Modbus-specific constants."""

CONF_ENTITIES = "registers"

TYPE_SIZES = {
    "uint16": 1,
    "int16": 1,
    "uint32": 2,
    "int32": 2,
    "float32": 2,
    "uint64": 4,
    "int64": 4,
}

def reg_key(name: str) -> str:
    """Generate consistent key from register name."""
    return name.lower().strip().replace(" ", "_")
