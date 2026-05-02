"""Tests for entity_base module: helpers, managers, and entity types."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.protocol_wizard.entity_base import (
    get_safe_number_defaults,
    apply_common_entity_attributes,
    set_readonly_protocol_settings,
)
from custom_components.protocol_wizard.sensor import SensorManager
from custom_components.protocol_wizard.number import NumberManager
from custom_components.protocol_wizard.switch import SwitchManager
from custom_components.protocol_wizard.select import SelectManager


# ---------------------------------------------------------------------------
# get_safe_number_defaults
# ---------------------------------------------------------------------------

class TestGetSafeNumberDefaults:
    """Test safe default min/max/step values for NumberEntity."""

    def test_uint16(self):
        d = get_safe_number_defaults("uint16")
        assert d["min"] == 0.0
        assert d["max"] == 65535.0
        assert d["step"] == 1.0

    def test_int16(self):
        d = get_safe_number_defaults("int16")
        assert d["min"] == -32768.0
        assert d["max"] == 32767.0

    def test_uint32(self):
        d = get_safe_number_defaults("uint32")
        assert d["min"] == 0.0
        assert d["max"] == 4294967295.0

    def test_int32(self):
        d = get_safe_number_defaults("int32")
        assert d["min"] == -2147483648.0
        assert d["max"] == 2147483647.0

    def test_uint64(self):
        d = get_safe_number_defaults("uint64")
        assert d["min"] == 0.0
        assert d["max"] > 1e18

    def test_int64(self):
        d = get_safe_number_defaults("int64")
        assert d["min"] < -9e17
        assert d["max"] > 9e17

    def test_float32(self):
        d = get_safe_number_defaults("float32")
        assert d["step"] == 0.1
        assert d["min"] == -1000000.0

    def test_unknown_type_defaults(self):
        d = get_safe_number_defaults("unknown_type")
        assert d["min"] == 0.0
        assert d["max"] == 100.0
        assert d["step"] == 1.0

    def test_case_insensitive(self):
        d = get_safe_number_defaults("UINT16")
        assert d["max"] == 65535.0


# ---------------------------------------------------------------------------
# apply_common_entity_attributes
# ---------------------------------------------------------------------------

class TestApplyCommonEntityAttributes:
    """Test applying common attributes to entities."""

    def _make_entity(self, entity_type="sensor"):
        """Create a mock entity with the right base classes."""
        from homeassistant.components.sensor import SensorEntity
        from homeassistant.components.number import NumberEntity

        if entity_type == "sensor":
            entity = MagicMock(spec=SensorEntity)
        elif entity_type == "number":
            entity = MagicMock(spec=NumberEntity)
        else:
            entity = MagicMock()
        return entity

    def test_device_class_applied(self):
        entity = self._make_entity()
        apply_common_entity_attributes(entity, {"device_class": "power"})
        assert entity._attr_device_class == "power"

    def test_icon_applied(self):
        entity = self._make_entity()
        apply_common_entity_attributes(entity, {"icon": "mdi:flash"})
        assert entity._attr_icon == "mdi:flash"

    def test_icon_not_set_when_empty(self):
        entity = self._make_entity()
        apply_common_entity_attributes(entity, {"icon": ""})
        # Should not set icon when empty string
        assert not hasattr(entity, "_attr_icon") or entity._attr_icon != ""

    def test_device_class_none(self):
        entity = self._make_entity()
        apply_common_entity_attributes(entity, {})
        assert entity._attr_device_class is None


# ---------------------------------------------------------------------------
# set_readonly_protocol_settings
# ---------------------------------------------------------------------------

class TestSetReadonlyProtocolSettings:
    """Test attaching protocol settings as extra state attributes."""

    def test_settings_attached(self):
        entity = MagicMock()
        entity._attr_extra_state_attributes = None
        config = {
            "address": 0,
            "register_type": "holding",
            "data_type": "uint16",
            "rw": "read",
            "scale": 1,
            "offset": 0,
        }
        set_readonly_protocol_settings(entity, config)
        attrs = entity._attr_extra_state_attributes
        assert "protocol_settings" in attrs
        settings = attrs["protocol_settings"]
        assert settings["address"] == 0
        assert settings["data_type"] == "uint16"

    def test_none_values_excluded(self):
        entity = MagicMock()
        entity._attr_extra_state_attributes = None
        config = {"address": 0, "scale": None}
        set_readonly_protocol_settings(entity, config)
        settings = entity._attr_extra_state_attributes["protocol_settings"]
        assert "scale" not in settings

    def test_preserves_existing_attrs(self):
        entity = MagicMock()
        entity._attr_extra_state_attributes = {"existing_key": "value"}
        set_readonly_protocol_settings(entity, {"address": 5})
        attrs = entity._attr_extra_state_attributes
        assert attrs["existing_key"] == "value"
        assert "protocol_settings" in attrs


# ---------------------------------------------------------------------------
# Entity Manager - _should_create_entity logic
# ---------------------------------------------------------------------------

class TestSensorManagerShouldCreate:
    """Test SensorManager entity creation logic."""

    def test_read_entity_creates_sensor(self):
        mgr = object.__new__(SensorManager)
        assert mgr._should_create_entity({"rw": "read"}) is True

    def test_rw_entity_creates_sensor(self):
        mgr = object.__new__(SensorManager)
        assert mgr._should_create_entity({"rw": "rw"}) is True

    def test_write_only_no_sensor(self):
        mgr = object.__new__(SensorManager)
        assert mgr._should_create_entity({"rw": "write"}) is False

    def test_default_rw_creates_sensor(self):
        mgr = object.__new__(SensorManager)
        # Default rw is "read"
        assert mgr._should_create_entity({}) is True


class TestNumberManagerShouldCreate:
    """Test NumberManager entity creation logic."""

    def test_write_holding_creates_number(self):
        mgr = object.__new__(NumberManager)
        assert mgr._should_create_entity({"rw": "write", "register_type": "holding"}) is True

    def test_rw_holding_creates_number(self):
        mgr = object.__new__(NumberManager)
        assert mgr._should_create_entity({"rw": "rw", "register_type": "holding"}) is True

    def test_read_only_no_number(self):
        mgr = object.__new__(NumberManager)
        assert mgr._should_create_entity({"rw": "read"}) is False

    def test_coil_no_number(self):
        mgr = object.__new__(NumberManager)
        assert mgr._should_create_entity({"rw": "write", "register_type": "coil"}) is False

    def test_with_options_no_number(self):
        mgr = object.__new__(NumberManager)
        assert mgr._should_create_entity({
            "rw": "write",
            "options": {"0": "Off", "1": "On"},
        }) is False

    def test_default_register_type_is_holding(self):
        mgr = object.__new__(NumberManager)
        # Default register_type is "holding", should create number
        assert mgr._should_create_entity({"rw": "write"}) is True


class TestSwitchManagerShouldCreate:
    """Test SwitchManager entity creation logic."""

    def test_coil_write_creates_switch(self):
        mgr = object.__new__(SwitchManager)
        assert mgr._should_create_entity({"rw": "write", "register_type": "coil"}) is True

    def test_coil_rw_creates_switch(self):
        mgr = object.__new__(SwitchManager)
        assert mgr._should_create_entity({"rw": "rw", "register_type": "coil"}) is True

    def test_coil_read_no_switch(self):
        mgr = object.__new__(SwitchManager)
        assert mgr._should_create_entity({"rw": "read", "register_type": "coil"}) is False

    def test_holding_no_switch(self):
        mgr = object.__new__(SwitchManager)
        assert mgr._should_create_entity({"rw": "write", "register_type": "holding"}) is False

    def test_coil_with_options_no_switch(self):
        mgr = object.__new__(SwitchManager)
        assert mgr._should_create_entity({
            "rw": "write",
            "register_type": "coil",
            "options": {"0": "Off", "1": "On"},
        }) is False


class TestSelectManagerShouldCreate:
    """Test SelectManager entity creation logic."""

    def test_write_with_options_creates_select(self):
        mgr = object.__new__(SelectManager)
        assert mgr._should_create_entity({
            "rw": "write",
            "options": {"0": "Off", "1": "On"},
        }) is True

    def test_rw_with_options_creates_select(self):
        mgr = object.__new__(SelectManager)
        assert mgr._should_create_entity({
            "rw": "rw",
            "options": {"0": "Off", "1": "On"},
        }) is True

    def test_read_with_options_no_select(self):
        mgr = object.__new__(SelectManager)
        assert mgr._should_create_entity({
            "rw": "read",
            "options": {"0": "Off", "1": "On"},
        }) is False

    def test_write_without_options_no_select(self):
        mgr = object.__new__(SelectManager)
        assert mgr._should_create_entity({"rw": "write"}) is False

    def test_empty_options_no_select(self):
        mgr = object.__new__(SelectManager)
        assert mgr._should_create_entity({"rw": "write", "options": {}}) is False


# ---------------------------------------------------------------------------
# Entity Manager - key generation
# ---------------------------------------------------------------------------

class TestEntityManagerKeyGeneration:
    """Test entity key and unique ID generation."""

    def _make_manager(self, protocol="modbus", slave_id=None):
        mgr = object.__new__(SensorManager)
        mgr.entry = MagicMock()
        mgr.entry.entry_id = "entry_abc"
        mgr.entry.data = {"protocol": protocol}
        mgr.coordinator = MagicMock()
        if slave_id is not None:
            mgr.coordinator.slave_id = slave_id
        else:
            # Remove slave_id attribute
            del mgr.coordinator.slave_id
        if hasattr(mgr.coordinator, "device_index"):
            del mgr.coordinator.device_index
        return mgr

    def test_entity_key_generation(self):
        mgr = self._make_manager()
        assert mgr._entity_key("Voltage Phase 1") == "voltage_phase_1"

    def test_entity_key_strips(self):
        mgr = self._make_manager()
        assert mgr._entity_key("  Power  ") == "power"

    def test_unique_id_without_slave(self):
        mgr = self._make_manager(slave_id=None)
        config = {"name": "Test", "address": 0, "register_type": "holding"}
        uid = mgr._unique_id(config)
        assert uid.startswith("entry_abc_")
        assert "test_" in uid
        assert uid.endswith("_sensor")

    def test_unique_id_with_slave(self):
        mgr = self._make_manager(slave_id=1)
        config = {"name": "Test", "address": 0, "register_type": "holding"}
        uid = mgr._unique_id(config)
        assert "s1_" in uid

    def test_unique_id_different_names_different_ids(self):
        mgr = self._make_manager()
        uid1 = mgr._unique_id({"name": "Sensor A", "address": 0})
        uid2 = mgr._unique_id({"name": "Sensor B", "address": 0})
        assert uid1 != uid2
