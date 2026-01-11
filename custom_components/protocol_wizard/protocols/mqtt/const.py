# custom_components/protocol_wizard/protocols/mqtt/const.py
"""Constants for MQTT protocol."""

# Config keys
CONF_ENTITIES = "entities"
CONF_BROKER = "broker"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_CLIENT_ID = "client_id"

# Default values
DEFAULT_PORT = 1883
DEFAULT_QOS = 0

# Data types
DATA_TYPES = [
    "string",
    "integer",
    "float",
    "boolean",
    "json",
]


def topic_key(name: str) -> str:
    """Generate a stable key from entity name."""
    return name.lower().strip().replace(" ", "_").replace("/", "_")
