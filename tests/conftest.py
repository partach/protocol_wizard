"""Shared fixtures for Protocol Wizard tests."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, PropertyMock, patch

import pytest

# Stub out homeassistant and third-party modules before any project import.
# This lets us unit-test pure logic without installing Home Assistant or
# protocol libraries.

_HA_STUBS: dict[str, MagicMock] = {}

_MODULES_TO_STUB = [
    # HA core
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.service",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.components.number",
    "homeassistant.components.select",
    "homeassistant.components.switch",
    "homeassistant.components.network",
    # Protocol libraries
    "pymodbus",
    "pymodbus.client",
    "pymodbus.client.mixin",
    "pymodbus.exceptions",
    "pysnmp",
    "pysnmp.hlapi",
    "pysnmp.hlapi.v3arch",
    "pysnmp.hlapi.v3arch.asyncio",
    "paho",
    "paho.mqtt",
    "paho.mqtt.client",
    "bacpypes3",
    "bacpypes3.app",
    "bacpypes3.primitivedata",
    "bacpypes3.basetypes",
    "bacpypes3.pdu",
    "bacpypes3.local",
    "bacpypes3.local.device",
    "bacpypes3.settings",
    "bacpypes3.argparse",
    "serial",
    "serial.tools",
    "serial.tools.list_ports",
    "voluptuous",
]


def _install_stubs():
    """Install stub modules into sys.modules so imports succeed."""
    for mod_name in _MODULES_TO_STUB:
        if mod_name not in sys.modules:
            mock = MagicMock()
            _HA_STUBS[mod_name] = mock
            sys.modules[mod_name] = mock

    # --- Provide realistic stub behaviour for key HA types ---

    # Platform enum
    platform_mock = MagicMock()
    platform_mock.SENSOR = "sensor"
    platform_mock.NUMBER = "number"
    platform_mock.SELECT = "select"
    platform_mock.SWITCH = "switch"
    sys.modules["homeassistant.const"].Platform = platform_mock

    # EntityCategory enum
    entity_category_mock = MagicMock()
    entity_category_mock.DIAGNOSTIC = "diagnostic"
    entity_category_mock.CONFIG = "config"
    sys.modules["homeassistant.helpers.entity"].EntityCategory = entity_category_mock

    # NumberMode enum
    number_mode_mock = MagicMock()
    number_mode_mock.BOX = "box"
    number_mode_mock.SLIDER = "slider"
    sys.modules["homeassistant.components.number"].NumberMode = number_mode_mock

    # DataUpdateCoordinator – just provide a simple base
    class _FakeDataUpdateCoordinator:
        def __init__(self, *args, **kwargs):
            self.data = {}
            self.last_update_success = True
            self.config_entry = kwargs.get("config_entry")

        async def async_request_refresh(self):
            pass

    sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = (
        _FakeDataUpdateCoordinator
    )

    # CoordinatorEntity – minimal
    class _FakeCoordinatorEntity:
        def __init__(self, coordinator, *args, **kwargs):
            self.coordinator = coordinator
            self.hass = getattr(coordinator, "hass", None)

    sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = (
        _FakeCoordinatorEntity
    )

    # Sensor / Number / Select / Switch base classes
    for mod_name, cls_name in [
        ("homeassistant.components.sensor", "SensorEntity"),
        ("homeassistant.components.number", "NumberEntity"),
        ("homeassistant.components.select", "SelectEntity"),
        ("homeassistant.components.switch", "SwitchEntity"),
    ]:
        setattr(sys.modules[mod_name], cls_name, type(cls_name, (), {}))

    # Entity base
    sys.modules["homeassistant.helpers.entity"].Entity = type("Entity", (), {})
    sys.modules["homeassistant.helpers.entity"].DeviceInfo = dict

    # ConfigEntry mock factory
    sys.modules["homeassistant.config_entries"].ConfigEntry = MagicMock

    # callback decorator – identity
    sys.modules["homeassistant.core"].callback = lambda fn: fn

    # async_dispatcher_connect – identity
    sys.modules["homeassistant.helpers.dispatcher"].async_dispatcher_connect = (
        MagicMock(return_value=MagicMock())
    )

    # entity_registry
    er_mock = sys.modules["homeassistant.helpers.entity_registry"]
    er_mock.async_get = MagicMock(return_value=MagicMock(entities=MagicMock(values=MagicMock(return_value=[]))))

    # ModbusClientMixin.DATATYPE
    datatype_mock = MagicMock()
    datatype_mock.UINT16 = "uint16"
    datatype_mock.INT16 = "int16"
    datatype_mock.UINT32 = "uint32"
    datatype_mock.INT32 = "int32"
    datatype_mock.FLOAT32 = "float32"
    datatype_mock.UINT64 = "uint64"
    datatype_mock.INT64 = "int64"
    datatype_mock.STRING = "string"
    mixin_mock = MagicMock()
    mixin_mock.DATATYPE = datatype_mock
    sys.modules["pymodbus.client.mixin"].ModbusClientMixin = mixin_mock

    # ModbusIOException
    sys.modules["pymodbus.exceptions"].ModbusIOException = type(
        "ModbusIOException", (IOError,), {}
    )

    # SupportsResponse
    sys.modules["homeassistant.helpers.service"].SupportsResponse = MagicMock()

    # HomeAssistantError
    sys.modules["homeassistant.exceptions"].HomeAssistantError = type(
        "HomeAssistantError", (Exception,), {}
    )


# Install stubs at import time so conftest and test modules can import project code.
_install_stubs()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_hass():
    """Return a minimal mock HomeAssistant object."""
    hass = MagicMock()
    hass.data = {}
    hass.config.path = MagicMock(side_effect=lambda *parts: "/".join(["/fake/ha"] + list(parts)))
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro)
    return hass


@pytest.fixture
def mock_config_entry():
    """Return a mock ConfigEntry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.title = "Test Device"
    entry.data = {
        "protocol": "modbus",
        "connection_type": "serial",
        "serial_port": "/dev/ttyUSB0",
        "baudrate": 9600,
        "parity": "N",
        "stopbits": 1,
        "bytesize": 8,
        "update_interval": 10,
    }
    entry.options = {}
    return entry
