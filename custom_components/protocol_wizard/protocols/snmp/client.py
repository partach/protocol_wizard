#------------------------------------------
#-- protocol snmp client.py protocol wizard
#------------------------------------------
"""SNMP protocol client implementation."""
from __future__ import annotations

import logging
from typing import Any

from pysnmp.hlapi.asyncio import (
    SnmpEngine,
    CommunityData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    getCmd,
    setCmd,
)

from ..base import BaseProtocolClient

_LOGGER = logging.getLogger(__name__)


class SNMPClient(BaseProtocolClient):
    """SNMP client implementation using pysnmp."""
    
    def __init__(
        self,
        host: str,
        port: int = 161,
        community: str = "public",
        version: str = "2c",
        timeout: int = 5,
        retries: int = 3,
    ):
        """
        Initialize SNMP client.
        
        Args:
            host: Target device hostname/IP
            port: SNMP port (default 161)
            community: SNMP community string (default "public")
            version: SNMP version - "1", "2c", or "3" (default "2c")
            timeout: Request timeout in seconds
            retries: Number of retries
        """
        self.host = host
        self.port = port
        self.community = community
        self.version = version
        self.timeout = timeout
        self.retries = retries
        self._connected = False
        
        # SNMP engine (reusable)
        self._engine = SnmpEngine()
        
        # Community data based on version
        if version in ("1", "2c"):
            self._community_data = CommunityData(community, mpModel=0 if version == "1" else 1)
        else:
            # SNMPv3 not implemented yet
            raise NotImplementedError("SNMPv3 support not yet implemented")
        
        # Transport target
        self._transport = UdpTransportTarget(
            (host, port),
            timeout=timeout,
            retries=retries,
        )
    
    async def connect(self) -> bool:
        """
        SNMP is connectionless, but we can verify reachability.
        Try reading sysDescr.0 (1.3.6.1.2.1.1.1.0) to verify.
        """
        try:
            # Test with sysDescr OID
            result = await self.read("1.3.6.1.2.1.1.1.0")
            if result is not None:
                self._connected = True
                _LOGGER.debug("SNMP connection verified for %s", self.host)
                return True
            return False
        except Exception as err:
            _LOGGER.error("SNMP connection test failed for %s: %s", self.host, err)
            self._connected = False
            return False
    
    async def disconnect(self) -> None:
        """Close SNMP engine."""
        try:
            # Unconfigure the SNMP engine to free resources
            self._engine.transportDispatcher.closeDispatcher()
            self._connected = False
        except Exception as err:
            _LOGGER.debug("Error closing SNMP engine: %s", err)
    
    async def read(self, address: str, **kwargs) -> Any:
        """
        Read SNMP OID.
        
        Args:
            address: OID string (e.g., "1.3.6.1.2.1.1.1.0" or "sysDescr.0")
            
        Returns:
            Raw value from SNMP GET, or None if error
        """
        try:
            iterator = getCmd(
                self._engine,
                self._community_data,
                self._transport,
                ContextData(),
                ObjectType(ObjectIdentity(address))
            )
            
            error_indication, error_status, error_index, var_binds = await iterator
            
            # Check for errors
            if error_indication:
                _LOGGER.error("SNMP error indication: %s", error_indication)
                return None
            
            if error_status:
                _LOGGER.error(
                    "SNMP error status: %s at %s",
                    error_status.prettyPrint(),
                    error_index and var_binds[int(error_index) - 1][0] or "?"
                )
                return None
            
            # Extract value from var_binds
            if var_binds:
                oid, value = var_binds[0]
                return value
            
            return None
            
        except Exception as err:
            _LOGGER.error("SNMP read failed for OID %s: %s", address, err)
            return None
    
    async def write(self, address: str, value: Any, **kwargs) -> bool:
        """
        Write SNMP OID (SNMP SET).
        
        Args:
            address: OID string
            value: Value to write
            
        Returns:
            True if successful
        """
        try:
            # Determine SNMP type from value
            # For now, let pysnmp infer the type
            iterator = setCmd(
                self._engine,
                self._community_data,
                self._transport,
                ContextData(),
                ObjectType(ObjectIdentity(address), value)
            )
            
            error_indication, error_status, error_index, var_binds = await iterator
            
            # Check for errors
            if error_indication:
                _LOGGER.error("SNMP SET error indication: %s", error_indication)
                return False
            
            if error_status:
                _LOGGER.error(
                    "SNMP SET error status: %s at %s",
                    error_status.prettyPrint(),
                    error_index and var_binds[int(error_index) - 1][0] or "?"
                )
                return False
            
            return True
            
        except Exception as err:
            _LOGGER.error("SNMP write failed for OID %s: %s", address, err)
            return False
    
    @property
    def is_connected(self) -> bool:
        """SNMP is connectionless, return cached connection test result."""
        return self._connected
