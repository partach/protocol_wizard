# custom_components/protocol_wizard/protocols/snmp/client.py
"""SNMP protocol client implementation."""
from __future__ import annotations

import asyncio
import logging
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
)

from ..base import BaseProtocolClient

_LOGGER = logging.getLogger(__name__)


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
    ):
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
        """Lazily create engine and transport."""
        async with self._engine_lock:
            if self._engine is None:
                self._engine = SnmpEngine()
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
        """Clean up SNMP engine."""
        if self._engine:
            try:
                self._engine.close_dispatcher()
            except Exception as err:
                _LOGGER.debug("Error closing SNMP dispatcher: %s", err)
            finally:
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
