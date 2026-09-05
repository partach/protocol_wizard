"""Tests for the shared, pre-warmed SNMP engine.

PySNMP loads bundled MIB modules from disk the first time an engine encodes a
request. Doing that on Home Assistant's event loop trips the "blocking call
inside the event loop" warnings, so the engine is created once in an executor
with its MIB modules preloaded.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from custom_components.protocol_wizard.protocols.snmp import client as snmp_client


@pytest.fixture(autouse=True)
def _reset_shared_engine():
    """Keep the process-wide engine cache out of other tests."""
    snmp_client._SNMP_ENGINE = None
    yield
    snmp_client._SNMP_ENGINE = None


class _FakeHass:
    """Minimal hass double that records executor usage."""

    def __init__(self):
        self.executor_calls = []

    async def async_add_executor_job(self, func, *args):
        self.executor_calls.append(func)
        return func(*args)


class TestCreateEngine:
    """Test _create_engine warm-up."""

    def test_preloads_bundled_mib_modules(self, monkeypatch):
        mib_builder = MagicMock()
        mib_builder.get_mib_sources.return_value = []
        engine = MagicMock()
        engine.get_mib_builder.return_value = mib_builder
        monkeypatch.setattr(snmp_client, "SnmpEngine", lambda: engine)

        assert snmp_client._create_engine() is engine

        loaded = [call.args[0] for call in mib_builder.load_modules.call_args_list]
        # The modules PySNMP would otherwise read lazily on the event loop.
        for module_name in ("SNMPv2-SMI", "SNMPv2-MIB", "SNMPv2-TM", "PYSNMP-SOURCE-MIB"):
            assert module_name in loaded
        # Each module is loaded at most once.
        assert len(loaded) == len(set(loaded))
        mib_builder.import_symbols.assert_called_once_with(
            "SNMPv2-MIB", "snmpInPkts", "snmpOutPkts"
        )

    def test_unloadable_module_does_not_raise(self, monkeypatch):
        mib_builder = MagicMock()
        mib_builder.get_mib_sources.return_value = []
        mib_builder.load_modules.side_effect = Exception("no such module")
        mib_builder.import_symbols.side_effect = Exception("no such symbol")
        engine = MagicMock()
        engine.get_mib_builder.return_value = mib_builder
        monkeypatch.setattr(snmp_client, "SnmpEngine", lambda: engine)

        assert snmp_client._create_engine() is engine


class TestIterMibModuleNames:
    """Test _iter_pysnmp_mib_module_names."""

    def test_discovers_module_names_from_file_sources(self, tmp_path):
        mib_dir = tmp_path / "mibs"
        mib_dir.mkdir()
        (mib_dir / "SNMPv2-MIB.py").write_text("")
        (mib_dir / "IF-MIB.py").write_text("")
        (mib_dir / "__init__.py").write_text("")
        (mib_dir / "notes.txt").write_text("")

        source = MagicMock()
        source._srcName = str(mib_dir)
        mib_builder = MagicMock()
        mib_builder.get_mib_sources.return_value = [source]

        names = set(snmp_client._iter_pysnmp_mib_module_names(mib_builder))
        assert names == {"SNMPv2-MIB", "IF-MIB"}

    def test_skips_non_file_sources(self, tmp_path):
        missing = MagicMock()
        missing._srcName = str(tmp_path / "does-not-exist")
        zipped = MagicMock()
        zipped._srcName = None
        mib_builder = MagicMock()
        mib_builder.get_mib_sources.return_value = [missing, zipped]

        assert list(snmp_client._iter_pysnmp_mib_module_names(mib_builder)) == []


class TestSharedEngine:
    """Test _async_get_shared_engine."""

    async def test_created_in_executor_and_cached(self, monkeypatch):
        engine = object()
        monkeypatch.setattr(snmp_client, "_create_engine", lambda: engine)
        hass = _FakeHass()

        first = await snmp_client._async_get_shared_engine(hass)
        second = await snmp_client._async_get_shared_engine(hass)

        assert first is engine
        assert second is engine
        # Built exactly once, and never on the event loop.
        assert len(hass.executor_calls) == 1

    async def test_falls_back_to_loop_executor_without_hass(self, monkeypatch):
        engine = object()
        creating_thread = []

        def _create():
            import threading

            creating_thread.append(threading.current_thread())
            return engine

        monkeypatch.setattr(snmp_client, "_create_engine", _create)

        result = await snmp_client._async_get_shared_engine()

        assert result is engine
        import threading

        assert creating_thread[0] is not threading.current_thread()

    async def test_concurrent_callers_share_one_engine(self, monkeypatch):
        calls = []

        def _create():
            calls.append(1)
            return object()

        monkeypatch.setattr(snmp_client, "_create_engine", _create)

        engines = await asyncio.gather(
            *(snmp_client._async_get_shared_engine() for _ in range(5))
        )

        assert len(calls) == 1
        assert len({id(e) for e in engines}) == 1


class TestClientUsesSharedEngine:
    """Test SNMPClient engine handling."""

    async def test_ensure_engine_uses_shared_engine(self, monkeypatch):
        engine = object()
        monkeypatch.setattr(snmp_client, "_create_engine", lambda: engine)

        async def _create_transport(*args, **kwargs):
            return MagicMock()

        monkeypatch.setattr(
            snmp_client.UdpTransportTarget, "create", _create_transport
        )

        hass = _FakeHass()
        first = snmp_client.SNMPClient(host="10.0.0.1", hass=hass)
        second = snmp_client.SNMPClient(host="10.0.0.2", hass=hass)

        await first._ensure_engine()
        await second._ensure_engine()

        assert first._engine is engine
        assert second._engine is engine
        assert first._transport is not second._transport
        assert len(hass.executor_calls) == 1

    async def test_disconnect_leaves_shared_engine_open(self, monkeypatch):
        engine = MagicMock()
        monkeypatch.setattr(snmp_client, "_create_engine", lambda: engine)

        async def _create_transport(*args, **kwargs):
            return MagicMock()

        monkeypatch.setattr(
            snmp_client.UdpTransportTarget, "create", _create_transport
        )

        keeper = snmp_client.SNMPClient(host="10.0.0.1")
        leaver = snmp_client.SNMPClient(host="10.0.0.2")
        await keeper._ensure_engine()
        await leaver._ensure_engine()

        await leaver.disconnect()

        # Unloading one config entry must not tear down the engine others use.
        engine.close_dispatcher.assert_not_called()
        assert leaver._engine is None
        assert leaver._transport is None
        assert leaver.is_connected is False
        assert keeper._engine is engine
        assert await snmp_client._async_get_shared_engine() is engine
