"""Tests for the protocol registry and base protocol abstractions."""
from __future__ import annotations

from custom_components.protocol_wizard.protocols import ProtocolRegistry
from custom_components.protocol_wizard.protocols.base import (
    _SafeFormatDict,
)


class TestSafeFormatDict:
    """Tests for _SafeFormatDict used in format_value."""

    def test_existing_key_returned(self):
        d = _SafeFormatDict(value=42)
        assert d["value"] == 42

    def test_missing_key_returns_placeholder(self):
        d = _SafeFormatDict(value=42)
        assert d["missing"] == "{missing}"

    def test_format_map_preserves_unknown_keys(self):
        d = _SafeFormatDict(value=10)
        result = "{value} and {unknown}".format_map(d)
        assert result == "10 and {unknown}"


class TestProtocolRegistry:
    """Tests for the ProtocolRegistry singleton."""

    def test_modbus_registered(self):
        # Modbus coordinator registers itself on import
        from custom_components.protocol_wizard.protocols.modbus.coordinator import (
            ModbusCoordinator,
        )
        cls = ProtocolRegistry.get_coordinator_class("modbus")
        assert cls is ModbusCoordinator

    def test_snmp_registered(self):
        from custom_components.protocol_wizard.protocols.snmp.coordinator import (
            SNMPCoordinator,
        )
        cls = ProtocolRegistry.get_coordinator_class("snmp")
        assert cls is SNMPCoordinator

    def test_mqtt_registered(self):
        from custom_components.protocol_wizard.protocols.mqtt.coordinator import (
            MQTTCoordinator,
        )
        cls = ProtocolRegistry.get_coordinator_class("mqtt")
        assert cls is MQTTCoordinator

    def test_bacnet_registered(self):
        from custom_components.protocol_wizard.protocols.bacnet.coordinator import (
            BACnetCoordinator,
        )
        cls = ProtocolRegistry.get_coordinator_class("bacnet")
        assert cls is BACnetCoordinator

    def test_unknown_protocol_returns_none(self):
        assert ProtocolRegistry.get_coordinator_class("nonexistent") is None

    def test_available_protocols_contains_all_four(self):
        available = ProtocolRegistry.available_protocols()
        for proto in ("modbus", "snmp", "mqtt", "bacnet"):
            assert proto in available

    def test_register_decorator_adds_new_protocol(self):
        """Ensure the @register decorator works for arbitrary names."""

        @ProtocolRegistry.register("test_proto")
        class FakeCoordinator:
            pass

        assert ProtocolRegistry.get_coordinator_class("test_proto") is FakeCoordinator
        # Clean up
        ProtocolRegistry._protocols.pop("test_proto", None)


class TestBaseProtocolCoordinatorFormatValue:
    """Tests for BaseProtocolCoordinator._format_value (non-abstract)."""

    def _make_coordinator(self):
        """Create a minimal concrete coordinator for testing _format_value."""
        from custom_components.protocol_wizard.protocols.modbus.coordinator import (
            ModbusCoordinator,
        )

        coord = object.__new__(ModbusCoordinator)
        # Manually init only what _format_value needs
        coord.protocol_name = "modbus"
        return coord

    def test_no_format_returns_value_unchanged(self):
        coord = self._make_coordinator()
        assert coord._format_value(42, {}) == 42
        assert coord._format_value(42, {"format": ""}) == 42
        assert coord._format_value(42, {"format": "  "}) == 42

    def test_time_format_seconds(self):
        coord = self._make_coordinator()
        # 90061 seconds = 1d 1h 1m 1s
        result = coord._format_value(90061, {"format": "{d}d {h}h {m}m {s}s"})
        assert result == "1d 1h 1m 1s"

    def test_time_format_hours_minutes(self):
        coord = self._make_coordinator()
        result = coord._format_value(3661, {"format": "{h}h {m}m"})
        assert result == "1h 1m"

    def test_string_upper_lower(self):
        coord = self._make_coordinator()
        result = coord._format_value("hello", {"format": "{upper}"})
        assert result == "HELLO"
        result = coord._format_value("HELLO", {"format": "{lower}"})
        assert result == "hello"

    def test_value_placeholder(self):
        coord = self._make_coordinator()
        result = coord._format_value(42, {"format": "Value is {value}"})
        assert result == "Value is 42"

    def test_leaked_format_returns_original(self):
        coord = self._make_coordinator()
        # If a placeholder like {unknown} leaks through, return original value
        result = coord._format_value(42, {"format": "{nonexistent_key}"})
        assert result == 42

    def test_format_with_none_value(self):
        coord = self._make_coordinator()
        # None can't be converted to float, should still work via value placeholder
        result = coord._format_value(None, {"format": "{value}"})
        assert result == "None"

    def test_format_error_returns_original(self):
        coord = self._make_coordinator()
        # Malformed format string
        result = coord._format_value(42, {"format": "{value:z}"})
        assert result == 42
