"""Tests for protocol-specific constants and helper functions."""
from __future__ import annotations

import pytest

from custom_components.protocol_wizard.const import (
    CONF_PROTOCOL_BACNET,
    CONF_PROTOCOL_MODBUS,
    CONF_PROTOCOL_MQTT,
    CONF_PROTOCOL_SNMP,
    DEFAULT_BAUDRATE,
    DEFAULT_SLAVE_ID,
    DEFAULT_TCP_PORT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    SIGNAL_ENTITY_SYNC,
)
from custom_components.protocol_wizard.protocols.bacnet.const import (
    BACNET_DATA_TYPES,
    BACNET_OBJECT_TYPES,
    entity_key,
    format_bacnet_address,
    parse_bacnet_address,
)
from custom_components.protocol_wizard.protocols.modbus.const import (
    TYPE_SIZES,
    reg_key,
)
from custom_components.protocol_wizard.protocols.mqtt.const import (
    DATA_TYPES as MQTT_DATA_TYPES,
)
from custom_components.protocol_wizard.protocols.mqtt.const import (
    topic_key,
)
from custom_components.protocol_wizard.protocols.snmp.const import (
    SNMP_DATA_TYPES,
    oid_key,
)


class TestDomainConstants:
    """Test global domain constants."""

    def test_domain_value(self):
        assert DOMAIN == "protocol_wizard"

    def test_signal_entity_sync_contains_domain(self):
        assert DOMAIN in SIGNAL_ENTITY_SYNC

    def test_protocol_names(self):
        assert CONF_PROTOCOL_MODBUS == "modbus"
        assert CONF_PROTOCOL_SNMP == "snmp"
        assert CONF_PROTOCOL_MQTT == "mqtt"
        assert CONF_PROTOCOL_BACNET == "bacnet"

    def test_defaults(self):
        assert DEFAULT_SLAVE_ID == 1
        assert DEFAULT_BAUDRATE == 9600
        assert DEFAULT_TCP_PORT == 502
        assert DEFAULT_UPDATE_INTERVAL == 10


class TestModbusConstants:
    """Test Modbus-specific constants."""

    def test_type_sizes_single_register(self):
        assert TYPE_SIZES["uint16"] == 1
        assert TYPE_SIZES["int16"] == 1

    def test_type_sizes_double_register(self):
        assert TYPE_SIZES["uint32"] == 2
        assert TYPE_SIZES["int32"] == 2
        assert TYPE_SIZES["float32"] == 2

    def test_type_sizes_quad_register(self):
        assert TYPE_SIZES["uint64"] == 4
        assert TYPE_SIZES["int64"] == 4

    def test_reg_key_basic(self):
        assert reg_key("Voltage Phase 1") == "voltage_phase_1"

    def test_reg_key_strips_whitespace(self):
        assert reg_key("  Power  ") == "power"

    def test_reg_key_lowercase(self):
        assert reg_key("TOTAL ENERGY") == "total_energy"


class TestSNMPConstants:
    """Test SNMP-specific constants."""

    def test_snmp_data_types_contain_common_types(self):
        assert "string" in SNMP_DATA_TYPES
        assert "integer" in SNMP_DATA_TYPES
        assert "counter32" in SNMP_DATA_TYPES
        assert "timeticks" in SNMP_DATA_TYPES

    def test_oid_key(self):
        assert oid_key("System Description") == "system_description"

    def test_oid_key_strips(self):
        assert oid_key("  Name  ") == "name"


class TestMQTTConstants:
    """Test MQTT-specific constants."""

    def test_mqtt_data_types(self):
        assert "string" in MQTT_DATA_TYPES
        assert "integer" in MQTT_DATA_TYPES
        assert "float" in MQTT_DATA_TYPES
        assert "boolean" in MQTT_DATA_TYPES
        assert "json" in MQTT_DATA_TYPES

    def test_topic_key(self):
        assert topic_key("Room Temperature") == "room_temperature"


class TestBACnetConstants:
    """Test BACnet-specific constants."""

    def test_parse_bacnet_address_valid(self):
        obj_type, instance, prop = parse_bacnet_address("analogInput:0:presentValue")
        assert obj_type == "analogInput"
        assert instance == 0
        assert prop == "presentValue"

    def test_parse_bacnet_address_with_spaces(self):
        obj_type, instance, prop = parse_bacnet_address(
            "binaryOutput : 5 : presentValue"
        )
        assert obj_type == "binaryOutput"
        assert instance == 5
        assert prop == "presentValue"

    def test_parse_bacnet_address_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid BACnet address"):
            parse_bacnet_address("invalidformat")

    def test_parse_bacnet_address_too_few_parts(self):
        with pytest.raises(ValueError):
            parse_bacnet_address("analogInput:0")

    def test_parse_bacnet_address_non_numeric_instance(self):
        with pytest.raises(ValueError):
            parse_bacnet_address("analogInput:abc:presentValue")

    def test_format_bacnet_address(self):
        result = format_bacnet_address("analogOutput", 3, "presentValue")
        assert result == "analogOutput:3:presentValue"

    def test_format_and_parse_roundtrip(self):
        addr = format_bacnet_address("binaryValue", 10, "statusFlags")
        obj_type, instance, prop = parse_bacnet_address(addr)
        assert obj_type == "binaryValue"
        assert instance == 10
        assert prop == "statusFlags"

    def test_entity_key(self):
        assert entity_key("Zone Temperature") == "zone_temperature"

    def test_bacnet_object_types_has_common_types(self):
        assert "analogInput" in BACNET_OBJECT_TYPES
        assert "binaryOutput" in BACNET_OBJECT_TYPES
        assert "device" in BACNET_OBJECT_TYPES

    def test_bacnet_data_types_has_common_types(self):
        assert "float" in BACNET_DATA_TYPES
        assert "integer" in BACNET_DATA_TYPES
        assert "boolean" in BACNET_DATA_TYPES
        assert "string" in BACNET_DATA_TYPES
