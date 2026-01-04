#------------------------------------------
#-- base const.py protocol wizard
#------------------------------------------
"""Constants for the Protocol Wizard integration."""

DOMAIN = "protocol_wizard"  # Keep existing domain for backward compatibility

# Connection types (still relevant for Modbus, may be used by other protocols)
CONNECTION_TYPE_SERIAL = "serial"
CONNECTION_TYPE_IP = "ip"
CONNECTION_TYPE_TCP = "tcp"
CONNECTION_TYPE_UDP = "udp"

# Common configuration keys (shared across protocols)
CONF_PROTOCOL = "protocol"
CONF_NAME = "name"
CONF_CONNECTION_TYPE = "connection_type"
CONF_UPDATE_INTERVAL = "update_interval"

# Modbus-specific configuration keys
CONF_SLAVE_ID = "slave_id"
CONF_FIRST_REG = "first_register"
CONF_FIRST_REG_SIZE = "first_register_size"

# Serial settings (Modbus)
CONF_SERIAL_PORT = "serial_port"
CONF_BAUDRATE = "baudrate"
CONF_PARITY = "parity"
CONF_STOPBITS = "stopbits"
CONF_BYTESIZE = "bytesize"

# TCP/IP settings (Modbus)
CONF_HOST = "host"
CONF_PORT = "port"

# Entity configuration
CONF_ENTITIES = "entities"  # Standard key for most protocols
CONF_REGISTERS = "registers"
CONF_PROTOCOL_MODBUS = "modbus"
CONF_PROTOCOL_SNMP = "snmp"
CONF_PROTOCOL = "protocol"

# Defaults
DEFAULT_SLAVE_ID = 1
DEFAULT_BAUDRATE = 9600
DEFAULT_TCP_PORT = 502
DEFAULT_STOPBITS = 1
DEFAULT_BYTESIZE = 8
DEFAULT_PARITY = "N"
DEFAULT_UPDATE_INTERVAL = 10
