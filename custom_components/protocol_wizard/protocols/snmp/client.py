# custom_components/protocol_wizard/protocols/snmp/client.py
"""SNMP protocol client implementation."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine,
    CommunityData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    get_cmd,
    set_cmd,
    walk_cmd,
)

from ..base import BaseProtocolClient

_LOGGER = logging.getLogger(__name__)

# A single PySNMP engine is shared by every SNMP client in this process. Creating
# one is expensive (it loads MIB modules from disk), so it is built once inside an
# executor and kept for the lifetime of the process.
_SNMP_ENGINE: SnmpEngine | None = None
_ENGINE_LOCK = asyncio.Lock()


def _iter_pysnmp_mib_module_names(mib_builder):
    """Yield bundled PySNMP MIB module names from file-backed MIB sources."""
    seen = set()

    for mib_source in mib_builder.get_mib_sources():
        source_dir = getattr(mib_source, "_srcName", None)
        if not source_dir or not os.path.isdir(source_dir):
            continue

        for _root, _dirs, files in os.walk(source_dir):
            for filename in files:
                if not filename.endswith(".py") or filename == "__init__.py":
                    continue

                module_name = os.path.splitext(filename)[0]
                if module_name not in seen:
                    seen.add(module_name)
                    yield module_name


def _create_engine() -> SnmpEngine:
    """Create and warm PySNMP's engine before it is used on the event loop."""
    engine = SnmpEngine()

    # PySNMP lazily loads bundled MIB modules during the first request and
    # response. Home Assistant flags those file reads when they happen on the
    # event loop, so force the lazy work into the executor with engine creation.
    mib_builder = engine.get_mib_builder()
    module_names = [
        "SNMPv2-SMI",
        "SNMPv2-TC",
        "SNMPv2-CONF",
        "SNMPv2-TM",
        "SNMPv2-MIB",
        "PYSNMP-SOURCE-MIB",
        "__SNMPv2-MIB",
    ]
    module_names.extend(_iter_pysnmp_mib_module_names(mib_builder))

    for module_name in dict.fromkeys(module_names):
        try:
            mib_builder.load_modules(module_name)
        except Exception as err:
            _LOGGER.debug("Unable to preload PySNMP MIB module %s: %s", module_name, err)

    try:
        mib_builder.import_symbols("SNMPv2-MIB", "snmpInPkts", "snmpOutPkts")
    except Exception as err:
        _LOGGER.debug("Unable to preload PySNMP MIB symbols: %s", err)

    return engine


async def _async_get_shared_engine(hass=None) -> SnmpEngine:
    """Return the process-wide SNMP engine, creating it off the event loop."""
    global _SNMP_ENGINE

    async with _ENGINE_LOCK:
        if _SNMP_ENGINE is None:
            if hass is not None:
                _SNMP_ENGINE = await hass.async_add_executor_job(_create_engine)
            else:
                loop = asyncio.get_running_loop()
                _SNMP_ENGINE = await loop.run_in_executor(None, _create_engine)
            _LOGGER.debug("SNMP engine created")

    return _SNMP_ENGINE


class SNMPClient(BaseProtocolClient):
    """SNMP client using pysnmp asyncio v3arch."""

    def __init__(
        self,
        host: str,
        port: int = 161,
        community: str = "public",
        version: str = "2c",
        timeout: float = 5.0,
        retries: int = 3,
        hass=None,
    ):
        self.hass = hass
        self.host = host
        self.port = port
        self.community = community
        self.version = version
        self.timeout = timeout
        self.retries = retries

        self._engine: SnmpEngine | None = None
        self._transport: UdpTransportTarget | None = None
        self._engine_lock = asyncio.Lock()
        self._connected = False

        if version not in ("1", "2c"):
            raise NotImplementedError("Only SNMP v1 and v2c are supported")

        self._community_data = CommunityData(
            community,
            mpModel=0 if version == "1" else 1,
        )
        self._context = ContextData()

    async def _ensure_engine(self) -> None:
        """Lazily attach the shared engine and create this client's transport."""
        async with self._engine_lock:
            if self._engine is None:
                # Engine creation reads MIB files from disk, so it is done once in
                # an executor rather than on Home Assistant's event loop.
                self._engine = await _async_get_shared_engine(self.hass)
                self._transport = await UdpTransportTarget.create(
                    (self.host, self.port),
                    timeout=self.timeout,
                    retries=self.retries,
                )
                _LOGGER.debug("SNMP engine initialized for %s:%s", self.host, self.port)

    async def connect(self) -> bool:
        """Test connectivity by reading sysDescr.0."""
        try:
            await self._ensure_engine()
            value = await self.read("1.3.6.1.2.1.1.1.0")  # sysDescr
            self._connected = value is not None
            return self._connected
        except Exception as err:
            _LOGGER.error("SNMP connection test failed for %s:%s: %s", self.host, self.port, err)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Release this client's SNMP resources.

        The engine is shared process-wide, so its dispatcher is deliberately left
        open here — closing it would break every other SNMP client still in use.
        """
        self._engine = None
        self._transport = None
        self._connected = False

    async def read(self, address: str, **kwargs) -> Any | None:
        """Read a single OID."""
        await self._ensure_engine()

        try:
            error_indication, error_status, error_index, var_binds = await get_cmd(
                self._engine,
                self._community_data,
                self._transport,
                self._context,
                ObjectType(ObjectIdentity(address)),
            )

            if error_indication:
                _LOGGER.error("SNMP error indication: %s", error_indication)
                return None
            if error_status:
                _LOGGER.error(
                    "SNMP error %s at %s",
                    error_status.prettyPrint(),
                    error_index and var_binds[int(error_index) - 1][0] or "?",
                )
                return None
            if var_binds:
                return var_binds[0][1]  # Return just the value
            return None

        except Exception as err:
            _LOGGER.error("SNMP read failed for OID %s: %s", address, err)
            return None
            
    async def walk(self, base_oid: str) -> list[Any]:
        """Perform SNMP walk on subtree.
        
        - Returns list of values if leaf node (single item)
        - Returns list of (oid, value) tuples for subtree items
        - Ignores 'No Such Instance' on base OID get
        """
        await self._ensure_engine()
        if not base_oid or not base_oid.strip():
            _LOGGER.debug("SNMP walk no oid %s", base_oid)
            return []
    
        results = []
    
        try:
            # Step 1: Try GET on the base OID itself (for leaf nodes)
            error_indication, error_status, error_index, var_binds = await get_cmd(
                self._engine,
                self._community_data,
                self._transport,
                self._context,
                ObjectType(ObjectIdentity(base_oid)),
            )
    
            # Only add the base value if GET succeeded (skip on 'No Such Instance')
            if not error_indication and not error_status and var_binds:
                _, value = var_binds[0]
                pretty_value = value.prettyPrint() if hasattr(value, 'prettyPrint') else str(value)
                if "No Such Instance currently exists at this OID" not in pretty_value:
                  results.append(pretty_value)  # Just the value, no OID
    
            # Step 2: Normal walk for subtree (always include OID + value)
            iterator = walk_cmd(
                self._engine,
                self._community_data,
                self._transport,
                self._context,
                ObjectType(ObjectIdentity(base_oid)),
                lexicographicMode=False,
                ignoreNonIncreasingOid=True,
            )
    
            async for error_indication, error_status, error_index, var_binds in iterator:
                if error_indication:
                    _LOGGER.error("SNMP walk error indication: %s", error_indication)
                    break
                if error_status:
                    break  # Normal end of MIB
                for var_bind in var_binds:
                    oid, value = var_bind
                    pretty_oid = oid.prettyPrint()
                    pretty_value = value.prettyPrint() if hasattr(value, 'prettyPrint') else str(value)
                    results.append((pretty_oid, pretty_value))
    
        except Exception as err:
            _LOGGER.error("SNMP walk failed for %s: %s", base_oid, err)
    
        return results
        
    async def write(self, address: str, value: Any, **kwargs) -> bool:
        """Write to a single OID."""
        await self._ensure_engine()

        try:
            error_indication, error_status, error_index, var_binds = await set_cmd(
                self._engine,
                self._community_data,
                self._transport,
                self._context,
                ObjectType(ObjectIdentity(address), value),
            )

            if error_indication:
                _LOGGER.error("SNMP SET error indication: %s", error_indication)
                return False
            if error_status:
                _LOGGER.error(
                    "SNMP SET error %s at %s",
                    error_status.prettyPrint(),
                    error_index and var_binds[int(error_index) - 1][0] or "?",
                )
                return False

            return True

        except Exception as err:
            _LOGGER.error("SNMP write failed for OID %s: %s", address, err)
            return False

    @property
    def is_connected(self) -> bool:
        """Return connection status."""
        return self._connected
