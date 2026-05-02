"""Tests for MQTT coordinator decode/encode/convert logic."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from custom_components.protocol_wizard.protocols.mqtt.coordinator import (
    MQTTCoordinator,
)


def _make_coordinator():
    """Create an MQTTCoordinator with minimal setup for testing."""
    coord = object.__new__(MQTTCoordinator)
    coord.protocol_name = "mqtt"
    coord.client = MagicMock()
    return coord


class TestMQTTConvertToType:
    """Test MQTTCoordinator._convert_to_type."""

    def test_convert_integer(self):
        coord = _make_coordinator()
        assert coord._convert_to_type("42", "integer") == 42
        assert coord._convert_to_type("3.7", "integer") == 3
        assert coord._convert_to_type(42.9, "integer") == 42

    def test_convert_float(self):
        coord = _make_coordinator()
        assert coord._convert_to_type("3.14", "float") == 3.14
        assert coord._convert_to_type(42, "float") == 42.0

    def test_convert_boolean_string_true(self):
        coord = _make_coordinator()
        for val in ("true", "1", "on", "yes", "True", "ON"):
            assert coord._convert_to_type(val, "boolean") is True, f"Failed for '{val}'"

    def test_convert_boolean_string_false(self):
        coord = _make_coordinator()
        for val in ("false", "0", "off", "no"):
            assert coord._convert_to_type(val, "boolean") is False, f"Failed for '{val}'"

    def test_convert_string(self):
        coord = _make_coordinator()
        assert coord._convert_to_type(42, "string") == "42"
        assert coord._convert_to_type("hello", "string") == "hello"

    def test_convert_string_numeric_entity(self):
        coord = _make_coordinator()
        # When expects_numeric, string data_type tries to convert to float
        assert coord._convert_to_type("42.5", "string", expects_numeric=True) == 42.5

    def test_convert_string_numeric_entity_non_numeric(self):
        coord = _make_coordinator()
        assert coord._convert_to_type("hello", "string", expects_numeric=True) is None

    def test_convert_json_string(self):
        coord = _make_coordinator()
        result = coord._convert_to_type('{"key": "val"}', "json")
        assert result == {"key": "val"}

    def test_convert_json_already_parsed(self):
        coord = _make_coordinator()
        data = {"key": "val"}
        assert coord._convert_to_type(data, "json") == data

    def test_convert_invalid_type_returns_value(self):
        coord = _make_coordinator()
        assert coord._convert_to_type("test", "unknown_type") == "test"

    def test_convert_error_numeric_returns_none(self):
        coord = _make_coordinator()
        assert coord._convert_to_type("abc", "integer", expects_numeric=True) is None


class TestMQTTDecodeValue:
    """Test MQTTCoordinator._decode_value."""

    def test_decode_none_returns_none(self):
        coord = _make_coordinator()
        assert coord._decode_value(None, {"data_type": "string"}) is None

    def test_decode_string_payload(self):
        coord = _make_coordinator()
        result = coord._decode_value("hello", {"data_type": "string"})
        assert result == "hello"

    def test_decode_integer_payload(self):
        coord = _make_coordinator()
        result = coord._decode_value("42", {"data_type": "integer"})
        assert result == 42

    def test_decode_float_payload(self):
        coord = _make_coordinator()
        result = coord._decode_value("3.14", {"data_type": "float"})
        assert result == 3.14

    def test_decode_boolean_payload(self):
        coord = _make_coordinator()
        assert coord._decode_value("true", {"data_type": "boolean"}) is True
        assert coord._decode_value("false", {"data_type": "boolean"}) is False

    def test_decode_json_string_payload(self):
        coord = _make_coordinator()
        result = coord._decode_value('{"temp": 22}', {"data_type": "json"})
        assert '"temp"' in result  # Should be formatted JSON string

    def test_decode_json_dict_payload(self):
        coord = _make_coordinator()
        data = {"temp": 22, "humidity": 55}
        result = coord._decode_value(data, {"data_type": "json"})
        assert isinstance(result, str)  # Should be JSON string
        parsed = json.loads(result)
        assert parsed["temp"] == 22

    def test_decode_dict_with_value_key_numeric(self):
        coord = _make_coordinator()
        result = coord._decode_value(
            {"value": 42}, {"data_type": "integer", "device_class": "temperature"}
        )
        assert result == 42

    def test_decode_list_first_element_numeric(self):
        coord = _make_coordinator()
        result = coord._decode_value(
            [42, 43], {"data_type": "integer", "device_class": "temperature"}
        )
        assert result == 42

    def test_decode_numeric_value_passthrough(self):
        coord = _make_coordinator()
        assert coord._decode_value(42, {"data_type": "integer"}) == 42
        assert coord._decode_value(3.14, {"data_type": "float"}) == 3.14

    def test_decode_bytes_returns_hex(self):
        coord = _make_coordinator()
        result = coord._decode_value(b"\xff\x00", {"data_type": "string"})
        assert result == "ff00"

    def test_decode_numeric_entity_string_value(self):
        coord = _make_coordinator()
        # String type with device_class (expects numeric)
        result = coord._decode_value(
            "22.5", {"data_type": "string", "device_class": "temperature"}
        )
        assert result == 22.5

    def test_decode_numeric_entity_non_numeric_string(self):
        coord = _make_coordinator()
        result = coord._decode_value(
            "not_a_number", {"data_type": "string", "device_class": "temperature"}
        )
        assert result is None


class TestMQTTEncodeValue:
    """Test MQTTCoordinator._encode_value."""

    def test_encode_string(self):
        coord = _make_coordinator()
        assert coord._encode_value("hello", {"data_type": "string"}) == "hello"
        assert coord._encode_value(42, {"data_type": "string"}) == "42"

    def test_encode_integer(self):
        coord = _make_coordinator()
        assert coord._encode_value("42.7", {"data_type": "integer"}) == 42
        assert coord._encode_value(42, {"data_type": "integer"}) == 42

    def test_encode_float(self):
        coord = _make_coordinator()
        assert coord._encode_value("3.14", {"data_type": "float"}) == 3.14

    def test_encode_boolean_string(self):
        coord = _make_coordinator()
        assert coord._encode_value("true", {"data_type": "boolean"}) is True
        assert coord._encode_value("false", {"data_type": "boolean"}) is False
        assert coord._encode_value("1", {"data_type": "boolean"}) is True
        assert coord._encode_value("0", {"data_type": "boolean"}) is False

    def test_encode_json_dict(self):
        coord = _make_coordinator()
        data = {"key": "value"}
        result = coord._encode_value(data, {"data_type": "json"})
        assert json.loads(result) == data

    def test_encode_json_string(self):
        coord = _make_coordinator()
        result = coord._encode_value('{"key": "value"}', {"data_type": "json"})
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_encode_invalid_value_returns_string(self):
        coord = _make_coordinator()
        result = coord._encode_value("abc", {"data_type": "integer"})
        assert result == "abc"  # Falls back to str


class TestMQTTExpectsNumeric:
    """Test MQTTCoordinator._expects_numeric."""

    def test_with_device_class(self):
        coord = _make_coordinator()
        assert coord._expects_numeric({"device_class": "temperature"}) is True

    def test_with_state_class(self):
        coord = _make_coordinator()
        assert coord._expects_numeric({"state_class": "measurement"}) is True

    def test_without_classes(self):
        coord = _make_coordinator()
        assert coord._expects_numeric({}) is False

    def test_with_both_classes(self):
        coord = _make_coordinator()
        assert coord._expects_numeric(
            {"device_class": "power", "state_class": "measurement"}
        ) is True
