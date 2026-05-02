"""Tests for SNMP coordinator decode/encode logic."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.protocol_wizard.protocols.snmp.coordinator import (
    SNMPCoordinator,
)


def _make_coordinator():
    """Create an SNMPCoordinator with minimal setup for testing."""
    coord = object.__new__(SNMPCoordinator)
    coord.protocol_name = "snmp"
    coord.client = MagicMock()
    return coord


class TestSNMPDecodeValue:
    """Test SNMPCoordinator._decode_value."""

    def test_decode_none_returns_none(self):
        coord = _make_coordinator()
        assert coord._decode_value(None, {"data_type": "string"}) is None

    def test_decode_string_with_pretty_print(self):
        coord = _make_coordinator()
        raw = MagicMock()
        raw.prettyPrint.return_value = "Linux router"
        result = coord._decode_value(raw, {"name": "sysDescr", "data_type": "string"})
        assert result == "Linux router"

    def test_decode_integer(self):
        coord = _make_coordinator()
        raw = MagicMock()
        raw.prettyPrint.return_value = "42"
        result = coord._decode_value(raw, {"name": "test", "data_type": "integer"})
        # int(42) * scale(1.0) + offset(0.0) = 42.0 (becomes float due to scale/offset)
        assert result == 42

    def test_decode_float(self):
        coord = _make_coordinator()
        raw = MagicMock()
        raw.prettyPrint.return_value = "3.14"
        result = coord._decode_value(raw, {"name": "test", "data_type": "float"})
        assert result == 3.14
        assert isinstance(result, float)

    def test_decode_counter32(self):
        coord = _make_coordinator()
        raw = MagicMock()
        raw.prettyPrint.return_value = "12345"
        result = coord._decode_value(raw, {"name": "test", "data_type": "counter32"})
        assert result == 12345

    def test_decode_gauge32(self):
        coord = _make_coordinator()
        raw = MagicMock()
        raw.prettyPrint.return_value = "99"
        result = coord._decode_value(raw, {"name": "test", "data_type": "gauge32"})
        assert result == 99

    def test_decode_timeticks(self):
        coord = _make_coordinator()
        raw = MagicMock()
        raw.prettyPrint.return_value = "100000"
        result = coord._decode_value(raw, {"name": "test", "data_type": "timeticks"})
        assert result == 100000

    def test_decode_with_scale_and_offset(self):
        coord = _make_coordinator()
        raw = MagicMock()
        raw.prettyPrint.return_value = "100"
        result = coord._decode_value(
            raw, {"name": "test", "data_type": "integer", "scale": 0.1, "offset": 5}
        )
        assert result == 100 * 0.1 + 5  # 15.0

    def test_decode_string_no_scale(self):
        coord = _make_coordinator()
        raw = MagicMock()
        raw.prettyPrint.return_value = "some text"
        result = coord._decode_value(
            raw, {"name": "test", "data_type": "string", "scale": 2}
        )
        # Strings should NOT have scale/offset applied
        assert result == "some text"

    def test_decode_invalid_integer_returns_none(self):
        coord = _make_coordinator()
        raw = MagicMock()
        raw.prettyPrint.return_value = "not_a_number"
        result = coord._decode_value(raw, {"name": "test", "data_type": "integer"})
        assert result is None

    def test_decode_without_pretty_print(self):
        coord = _make_coordinator()
        raw = "plain string"
        result = coord._decode_value(raw, {"name": "test", "data_type": "string"})
        assert result == "plain string"


class TestSNMPEncodeValue:
    """Test SNMPCoordinator._encode_value."""

    def test_encode_integer_with_reverse_scale(self):
        coord = _make_coordinator()
        result = coord._encode_value(
            15.0, {"data_type": "integer", "scale": 0.1, "offset": 5}
        )
        # (15 - 5) / 0.1 = 100, then int(round(100)) = 100
        assert result == 100

    def test_encode_float_with_reverse_scale(self):
        coord = _make_coordinator()
        result = coord._encode_value(
            15.0, {"data_type": "float", "scale": 0.1, "offset": 5}
        )
        # (15 - 5) / 0.1 = 100.0
        assert result == 100.0

    def test_encode_string_unchanged(self):
        coord = _make_coordinator()
        result = coord._encode_value("hello", {"data_type": "string"})
        assert result == "hello"

    def test_encode_counter32(self):
        coord = _make_coordinator()
        result = coord._encode_value(42, {"data_type": "counter32"})
        assert result == 42

    def test_encode_no_scale_offset(self):
        coord = _make_coordinator()
        result = coord._encode_value(50, {"data_type": "integer"})
        assert result == 50

    def test_encode_zero_scale_no_division(self):
        coord = _make_coordinator()
        # scale=0 should NOT divide by zero
        result = coord._encode_value(50, {"data_type": "integer", "scale": 0})
        # Should return original value since scale=0 skips division
        assert result == 50
