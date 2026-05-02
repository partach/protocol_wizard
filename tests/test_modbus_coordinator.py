"""Tests for Modbus coordinator decode/encode logic."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.protocol_wizard.protocols.modbus.coordinator import (
    ModbusCoordinator,
)


def _make_coordinator():
    """Create a ModbusCoordinator with minimal setup for testing decode/encode."""
    coord = object.__new__(ModbusCoordinator)
    coord.protocol_name = "modbus"

    # Mock the client and its raw_client
    coord.client = MagicMock()
    raw_client = MagicMock()
    coord.client.raw_client = raw_client
    return coord


class TestModbusDecodeValue:
    """Test ModbusCoordinator._decode_value."""

    def test_decode_bool_single_true(self):
        coord = _make_coordinator()
        result = coord._decode_value([True], {"data_type": "uint16"})
        assert result is True

    def test_decode_bool_single_false(self):
        coord = _make_coordinator()
        result = coord._decode_value([False], {"data_type": "uint16"})
        assert result is False

    def test_decode_bool_multi_bit(self):
        coord = _make_coordinator()
        # [True, False, True] reversed -> "101" = 5
        result = coord._decode_value([True, False, True], {"data_type": "uint16"})
        assert result == 5

    def test_decode_empty_values_returns_none(self):
        coord = _make_coordinator()
        result = coord._decode_value([], {"data_type": "uint16"})
        assert result is None

    def test_decode_none_returns_none(self):
        coord = _make_coordinator()
        result = coord._decode_value(None, {"data_type": "uint16"})
        assert result is None

    def test_decode_uint16_calls_convert(self):
        coord = _make_coordinator()
        coord.client.raw_client.convert_from_registers.return_value = 42
        result = coord._decode_value([42], {"data_type": "uint16"})
        assert result == 42
        coord.client.raw_client.convert_from_registers.assert_called_once()

    def test_decode_with_scale_and_offset(self):
        coord = _make_coordinator()
        coord.client.raw_client.convert_from_registers.return_value = 100
        result = coord._decode_value(
            [100], {"data_type": "uint16", "scale": 0.1, "offset": 5}
        )
        assert result == 100 * 0.1 + 5  # 15.0

    def test_decode_float32_rounded(self):
        coord = _make_coordinator()
        coord.client.raw_client.convert_from_registers.return_value = 3.14159265
        result = coord._decode_value(
            [0x4049, 0x0FD0], {"data_type": "float32"}
        )
        # Should be rounded to 6 decimal places
        assert isinstance(result, float)

    def test_decode_string_strips_nulls(self):
        coord = _make_coordinator()
        coord.client.raw_client.convert_from_registers.return_value = "hello\x00\x00"
        result = coord._decode_value([0x6865, 0x6C6C, 0x6F00], {"data_type": "string"})
        assert result == "hello"

    def test_decode_integer_preserves_int_type(self):
        coord = _make_coordinator()
        coord.client.raw_client.convert_from_registers.return_value = 100
        result = coord._decode_value([100], {"data_type": "uint16", "scale": 2})
        # 100 * 2 = 200.0, but should be int since data_type is integer
        assert result == 200
        assert isinstance(result, int)

    def test_decode_too_few_registers_returns_none(self):
        coord = _make_coordinator()
        # uint32 needs 2 registers but only 1 provided
        result = coord._decode_value([42], {"data_type": "uint32"})
        assert result is None

    def test_decode_with_word_order_little(self):
        coord = _make_coordinator()
        coord.client.raw_client.convert_from_registers.return_value = 42
        coord._decode_value([0, 42], {"data_type": "uint32", "word_order": "little"})
        call_args = coord.client.raw_client.convert_from_registers.call_args
        assert call_args.kwargs.get("word_order", call_args[1].get("word_order")) == 1

    def test_decode_with_word_order_big(self):
        coord = _make_coordinator()
        coord.client.raw_client.convert_from_registers.return_value = 42
        coord._decode_value([42, 0], {"data_type": "uint32", "word_order": "big"})
        call_args = coord.client.raw_client.convert_from_registers.call_args
        assert call_args.kwargs.get("word_order", call_args[1].get("word_order")) == 0

    def test_decode_exception_returns_none(self):
        coord = _make_coordinator()
        coord.client.raw_client.convert_from_registers.side_effect = Exception("fail")
        result = coord._decode_value([42], {"data_type": "uint16"})
        assert result is None


class TestModbusEncodeValue:
    """Test ModbusCoordinator._encode_value."""

    def test_encode_coil_true_values(self):
        coord = _make_coordinator()
        for val in ("true", "1", "on", "yes", "True", "ON"):
            result = coord._encode_value(val, {"register_type": "coil", "data_type": "uint16"})
            assert result is True, f"Failed for '{val}'"

    def test_encode_coil_false_values(self):
        coord = _make_coordinator()
        for val in ("false", "0", "off", "no", "False", "OFF"):
            result = coord._encode_value(val, {"register_type": "coil", "data_type": "uint16"})
            assert result is False, f"Failed for '{val}'"

    def test_encode_coil_bool(self):
        coord = _make_coordinator()
        assert coord._encode_value(True, {"register_type": "coil", "data_type": "uint16"}) is True
        assert coord._encode_value(False, {"register_type": "coil", "data_type": "uint16"}) is False

    def test_encode_coil_invalid_string(self):
        coord = _make_coordinator()
        result = coord._encode_value("invalid", {"register_type": "coil", "data_type": "uint16"})
        assert result is None

    def test_encode_uint16_returns_list(self):
        coord = _make_coordinator()
        result = coord._encode_value(42, {"data_type": "uint16"})
        assert result == [42]

    def test_encode_int16_negative(self):
        coord = _make_coordinator()
        result = coord._encode_value(-1, {"data_type": "int16"})
        assert result == [65535]

    def test_encode_uint16_clamps_max(self):
        coord = _make_coordinator()
        result = coord._encode_value(70000, {"data_type": "uint16"})
        assert result == [65535]

    def test_encode_string_true_to_one(self):
        coord = _make_coordinator()
        result = coord._encode_value("true", {"data_type": "uint16"})
        assert result == [1]

    def test_encode_string_false_to_zero(self):
        coord = _make_coordinator()
        result = coord._encode_value("false", {"data_type": "uint16"})
        assert result == [0]

    def test_encode_with_reverse_scale_offset(self):
        coord = _make_coordinator()
        # value=15, offset=5, scale=0.1 -> (15-5)/0.1 = 100
        result = coord._encode_value(15, {"data_type": "uint16", "scale": 0.1, "offset": 5})
        assert result == [100]

    def test_encode_float32_calls_convert(self):
        coord = _make_coordinator()
        coord.client.raw_client.convert_to_registers.return_value = [0x4049, 0x0FD0]
        result = coord._encode_value(3.14, {"data_type": "float32"})
        assert result == [0x4049, 0x0FD0]

    def test_encode_non_numeric_string_returns_none(self):
        coord = _make_coordinator()
        result = coord._encode_value("abc", {"data_type": "uint16"})
        assert result is None

    def test_encode_uint32_calls_convert(self):
        coord = _make_coordinator()
        coord.client.raw_client.convert_to_registers.return_value = [0, 100]
        result = coord._encode_value(100, {"data_type": "uint32"})
        assert result == [0, 100]
