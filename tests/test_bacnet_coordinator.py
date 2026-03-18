"""Tests for BACnet coordinator decode/encode logic."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from custom_components.protocol_wizard.protocols.bacnet.coordinator import (
    BACnetCoordinator,
)


def _make_coordinator():
    """Create a BACnetCoordinator with minimal setup for testing."""
    coord = object.__new__(BACnetCoordinator)
    coord.protocol_name = "bacnet"
    coord.client = MagicMock()
    return coord


class TestBACnetDecodeValue:
    """Test BACnetCoordinator._decode_value."""

    def test_decode_float(self):
        coord = _make_coordinator()
        result = coord._decode_value(22.5, {"data_type": "float"})
        assert result == 22.5
        assert isinstance(result, float)

    def test_decode_integer(self):
        coord = _make_coordinator()
        result = coord._decode_value(42, {"data_type": "integer"})
        assert result == 42
        assert isinstance(result, int)

    def test_decode_string(self):
        coord = _make_coordinator()
        result = coord._decode_value("Room 101", {"data_type": "string"})
        assert result == "Room 101"

    def test_decode_boolean_true(self):
        coord = _make_coordinator()
        assert coord._decode_value(True, {"data_type": "boolean"}) is True

    def test_decode_boolean_false(self):
        coord = _make_coordinator()
        assert coord._decode_value(False, {"data_type": "boolean"}) is False

    def test_decode_boolean_string_active(self):
        coord = _make_coordinator()
        result = coord._decode_value("active", {"data_type": "boolean"})
        assert result == "active"

    def test_decode_boolean_string_inactive(self):
        coord = _make_coordinator()
        result = coord._decode_value("inactive", {"data_type": "boolean"})
        assert result == "inactive"

    def test_decode_boolean_from_int(self):
        coord = _make_coordinator()
        assert coord._decode_value(1, {"data_type": "boolean"}) is True
        assert coord._decode_value(0, {"data_type": "boolean"}) is False

    def test_decode_boolean_from_string(self):
        coord = _make_coordinator()
        assert coord._decode_value("true", {"data_type": "boolean"}) is True
        assert coord._decode_value("false", {"data_type": "boolean"}) is False

    def test_decode_enumerated(self):
        coord = _make_coordinator()
        result = coord._decode_value(3, {"data_type": "enumerated"})
        assert result == 3

    def test_decode_unsigned(self):
        coord = _make_coordinator()
        result = coord._decode_value(100, {"data_type": "unsigned"})
        assert result == 100

    def test_decode_with_scale(self):
        coord = _make_coordinator()
        result = coord._decode_value(100, {"data_type": "float", "scale": 0.1})
        assert result == pytest.approx(10.0)

    def test_decode_with_offset(self):
        coord = _make_coordinator()
        result = coord._decode_value(100, {"data_type": "float", "offset": 5.0})
        assert result == 105.0

    def test_decode_with_scale_and_offset(self):
        coord = _make_coordinator()
        result = coord._decode_value(
            100, {"data_type": "float", "scale": 0.1, "offset": 5}
        )
        assert result == pytest.approx(15.0)

    def test_decode_boolean_no_scale(self):
        coord = _make_coordinator()
        # Booleans should NOT have scale/offset applied
        result = coord._decode_value(True, {"data_type": "boolean", "scale": 10})
        assert result is True

    def test_decode_type_conversion_error_returns_raw(self):
        coord = _make_coordinator()
        result = coord._decode_value("not_a_number", {"data_type": "integer"})
        assert result == "not_a_number"


class TestBACnetEncodeValue:
    """Test BACnetCoordinator._encode_value."""

    def test_encode_float(self):
        coord = _make_coordinator()
        result = coord._encode_value(22.5, {"data_type": "float"})
        assert result == 22.5
        assert isinstance(result, float)

    def test_encode_integer(self):
        coord = _make_coordinator()
        result = coord._encode_value(42, {"data_type": "integer"})
        assert result == 42
        assert isinstance(result, int)

    def test_encode_string(self):
        coord = _make_coordinator()
        result = coord._encode_value("Room 101", {"data_type": "string"})
        assert result == "Room 101"

    def test_encode_boolean_active(self):
        coord = _make_coordinator()
        result = coord._encode_value(True, {"data_type": "boolean"})
        assert result == "active"

    def test_encode_boolean_inactive(self):
        coord = _make_coordinator()
        result = coord._encode_value(False, {"data_type": "boolean"})
        assert result == "inactive"

    def test_encode_boolean_string_active_passthrough(self):
        coord = _make_coordinator()
        result = coord._encode_value("active", {"data_type": "boolean"})
        assert result == "active"

    def test_encode_boolean_from_string_1(self):
        coord = _make_coordinator()
        result = coord._encode_value("1", {"data_type": "boolean"})
        assert result == "active"

    def test_encode_boolean_from_string_on(self):
        coord = _make_coordinator()
        result = coord._encode_value("on", {"data_type": "boolean"})
        assert result == "active"  # "on" is in the explicit true list ("on", "On")

    def test_encode_enumerated(self):
        coord = _make_coordinator()
        result = coord._encode_value(3, {"data_type": "enumerated"})
        assert result == 3
        assert isinstance(result, int)

    def test_encode_unsigned(self):
        coord = _make_coordinator()
        result = coord._encode_value(100, {"data_type": "enum"})
        assert result == 100

    def test_encode_with_reverse_scale_offset(self):
        coord = _make_coordinator()
        # value=15, offset=5, scale=0.1 -> (15-5)/0.1 = 100.0
        result = coord._encode_value(
            15.0, {"data_type": "float", "scale": 0.1, "offset": 5.0}
        )
        assert result == pytest.approx(100.0)

    def test_encode_boolean_no_reverse_scale(self):
        coord = _make_coordinator()
        # Boolean should NOT reverse scale/offset
        result = coord._encode_value(True, {"data_type": "boolean", "scale": 10})
        assert result == "active"

    def test_encode_conversion_failure_returns_original(self):
        coord = _make_coordinator()
        result = coord._encode_value("not_a_number", {"data_type": "integer"})
        # Should return original value when conversion fails
        assert result == "not_a_number"
