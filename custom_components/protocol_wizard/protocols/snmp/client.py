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
    """SNMP client implementation using pysnmp (asyncio)."""

    def __init__(
        self,
        host: str,
        port: int = 161,
        community: str = "public",
        version: str = "2c",
        timeout: int = 5,
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

        if version in ("1", "2c"):
            self._community_data = CommunityData(
                community,
                mpModel=0 if version == "1" else 1,
            )
        else:
            raise NotImplementedError("SNMPv3 not yet implemented")

        self._context = ContextData()

    async def _ensure_engine(self) -> None:
        async with self._engine_lock:
            if self._engine is None:
                self._engine = SnmpEngine()
                self._transport = await UdpTransportTarget.create(
                    (self.host, self.port),
                    timeout=self.timeout,
                    retries=self.retries,
                )
                _LOGGER.debug("SNMP engine initialized for %s", self.host)

    async def connect(self) -> bool:
        """Verify SNMP reachability using sysDescr.0."""
        try:
            await self._ensure_engine()
            value = await self.read("1.3.6.1.2.1.1.1.0")
            self._connected = value is not None
            return self._connected
        except Exception as err:
            _LOGGER.error("SNMP connect failed for %s: %s", self.host, err)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close SNMP engine."""
        if self._engine:
            try:
                self._engine.transportDispatcher.closeDispatcher()
            except Exception as err:
                _LOGGER.debug("SNMP dispatcher close error: %s", err)
        self._engine = None
        self._transport = None
        self._connected = False

    async def read(self, address: str, **kwargs) -> Any | None:
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
                _LOGGER.error("SNMP error: %s", error_indication)
                return None

            if error_status:
                _LOGGER.error(
                    "SNMP error %s at %s",
                    error_status.prettyPrint(),
                    error_index and var_binds[int(error_index) - 1][0] or "?",
                )
                return None

            if var_binds:
                _, value = var_binds[0]
                return value

            return None

        except Exception as err:
            _LOGGER.error("SNMP read failed for %s: %s", address, err)
            return None

    async def write(self, address: str, value: Any, **kwargs) -> bool:
        await self._ensure_engine()

        try:
            error_indication, error_status, error_index, var_binds = await set_cmd(
                self._engine,
                self._community_data,
                self._transport,
                self._context,
                ObjectType(ObjectIdentity(address), value),
            )

            if error_indication or error_status:
                _LOGGER.error("SNMP SET failed for %s", address)
                return False

            return True

        except Exception as err:
            _LOGGER.error("SNMP write failed for %s: %s", address, err)
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected
