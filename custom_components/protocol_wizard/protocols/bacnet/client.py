# protocols/bacnet/client.py
"""BACnet/IP client for Protocol Wizard using bacpypes3 - proper initialization."""

import logging
import asyncio
from typing import Any, Optional
from homeassistant.core import HomeAssistant
from homeassistant.components.network import async_get_source_ip, async_get_adapters
#import sys

_LOGGER = logging.getLogger(__name__)

try:
#    from bacpypes3.settings import settings
    from bacpypes3.app import Application
#    from bacpypes3.local.device import DeviceObject
    from bacpypes3.primitivedata import ObjectIdentifier
    from bacpypes3.basetypes import PropertyIdentifier
    from bacpypes3.pdu import Address, LocalBroadcast
#    from bacpypes3.argparse import SimpleArgumentParser, create_log_handler
    import ipaddress
    HAS_BACPYPES3 = True
except ImportError:
    HAS_BACPYPES3 = False
    _LOGGER.error("bacpypes3 library not installed")

async def get_my_network_summary(hass):
    
    adapters = await async_get_adapters(hass)
    
    summary = []
    for adapter in adapters:
        if adapter["enabled"]:
            for ip_info in adapter["ipv4"]:
                summary.append({
                    "name": adapter["name"],
                    "ip": ip_info["address"],
                    "prefix": ip_info["network_prefix"],  # e.g. 24 for 255.255.255.0 (/24)
                    "subnet_mask": f"/{ip_info['network_prefix']}",
                    "default": adapter["default"]
                })
    return summary


async def get_my_lan_ip_and_subnet(hass):
    """
    Returns the preferred LAN IP + subnet prefix (e.g. "192.168.1.185/24")
    Prioritizes default interface, then private LAN ranges (192.168.*, 10.*, 172.*).
    """
    summary = await get_my_network_summary(hass)

    if not summary:
        return None, None

    # 1. Prefer default interface
    for entry in summary:
        if entry["default"]:
            return entry["ip"], entry["prefix"]

    # 2. Fallback: first private LAN IP
    for entry in summary:
        ip = entry["ip"]
        if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
            return entry["ip"], entry["prefix"]

    # 3. Last resort: first IP
    return summary[0]["ip"], summary[0]["prefix"]


def calculate_broadcast_address(ip_with_subnet):
    """
    Calculate broadcast address from IP/subnet (e.g. "192.168.1.185/24" -> "192.168.1.255")
    Returns tuple of (ip, subnet_mask, broadcast_address)
    """
    try:
        network = ipaddress.IPv4Network(ip_with_subnet, strict=False)
        ip = str(network.network_address + 1) if str(network.network_address).endswith('.0') else ip_with_subnet.split('/')[0]
        broadcast = str(network.broadcast_address)
        netmask = str(network.netmask)

        _LOGGER.debug("Network: %s, Broadcast: %s", network.network_address, broadcast)

        return ip, netmask, broadcast
    except Exception as e:
        _LOGGER.error("Failed to calculate broadcast address from %s: %s", ip_with_subnet, e)
        return None, None, None
    



class BACnetClientApp(Application):
    """BACnet client application following bacpypes3 patterns."""

    def __init__(self):
        """Initialize with proper setup."""
        Application.__init__(self)


class BACnetClient:
    """BACnet/IP client using bacpypes3."""
    
    def __init__(
        self, 
        hass: HomeAssistant,
        host: str, 
        device_id: Optional[int] = None,
        port: int = 47808,
        network_number: Optional[int] = 0
    ):
        """Initialize BACnet client."""
        if not HAS_BACPYPES3:
            raise ImportError("bacpypes3 library is required for BACnet support")
        
        self.host = host
        self.device_id = device_id
        self.port = port
        self.network_number = network_number
        self.app: Optional[Application] = None
        self._connected = False
        self.hass = hass
        self._bacpypeinstance = None
    
    async def _initialize_bacpypes3(self, hass: HomeAssistant):
        """Initialize bacpypes3 properly using from_args pattern."""
        if not self._bacpypeinstance:
            try:
                from argparse import Namespace
                import random
        
                source_ip = address_adapter = ip_to_use = self.host
                broadcast_addr = None

                try:
                    address_adapter = await get_my_lan_ip_and_subnet(hass)
                except Exception as err:
                    _LOGGER.warning("Error in getting adapter info: %s",  err)
                try:
                    source_ip = await async_get_source_ip(hass)
                except Exception as err:
                    _LOGGER.warning("Error in getting HA local IP info: %s",  err)

                if self.host == "0.0.0.0": # Discovery mode - use actual IP
                    if address_adapter and address_adapter[0]:
                        ip_with_subnet = f"{address_adapter[0]}/{address_adapter[1]}"
                        ip_to_use = ip_with_subnet
                        ip, netmask, broadcast = calculate_broadcast_address(ip_with_subnet)
                        if broadcast:
                            broadcast_addr = broadcast
                    else:
                        _LOGGER.error("Cannot use 0.0.0.0 - no network adapter found!")
                        raise ValueError("Discovery requires valid network interface")

                elif address_adapter[0]:
                    ip_with_subnet = f"{address_adapter[0]}/{address_adapter[1]}"
                    ip_to_use = ip_with_subnet
                    ip, netmask, broadcast = calculate_broadcast_address(ip_with_subnet)
                    if broadcast:
                        broadcast_addr = broadcast

                elif source_ip:
                    ip_to_use = source_ip
                    _LOGGER.warning("Using source_ip without subnet: %s (broadcast may not work!)", source_ip)

                _LOGGER.debug("BACnet binding to address: %s", ip_to_use)
                # Create a proper Namespace with required arguments
                # CRITICAL: Specify the correct network address to use
                # Use the actual HA IP address on the correct subnet
                args = Namespace(
                    # Required
                    name="Protocol Wizard Client",
                    instance=random.randint(100000, 999999),
                    vendoridentifier=999,
                    address=f"{ip_to_use}",
                    network=self.network_number,
                    
                    # Optional
                    foreign=None,
                    ttl=30,
                    bbmd=None,
                    
                    # Logging (set to None/False to avoid log handler issues)
                    loggers=None,
                    debug=None,
                    color=None,
                    route_aware=None,
                )
                
                _LOGGER.debug("Creating BACnet application with instance=%s, address=%s",
                            args.instance, args.address)

                theApp = Application.from_args(args)
                _LOGGER.debug("BACnet application initialized")

                return theApp
                
            except Exception as err:
                _LOGGER.error("Failed to initialize bacpypes3: %s", err)
                import traceback
                traceback.print_exc()
        
        return None
    
    async def connect(self) -> bool:
        """Connect to BACnet network."""
        try:
            self._bacpypeinstance = await self._initialize_bacpypes3(self.hass)

            if self._bacpypeinstance is None:
                _LOGGER.error("Failed to create BACnet application")
                return False

            self.app = self._bacpypeinstance
            self._connected = True
            _LOGGER.debug("BACnet connected")
            return True

        except Exception as err:
            _LOGGER.error("BACnet connection failed: %s", err)
            return False
    
    
    async def discover_devices(self, timeout: int = 10) -> list[dict]:
        """Discover BACnet devices using Who-Is."""
        try:
            _LOGGER.debug("Starting BACnet device discovery (timeout: %ds)", timeout)

            if not self.app:
                await self.connect()

            if not self.app:
                _LOGGER.error("Cannot discover without BACnet connection")
                return []

            try:
                if self.host != "0.0.0.0" and self.device_id:
                    target_address = Address(f"{self.host}:{self.port}")
                    await self.app.who_is(
                        device_instance_range_low_limit=self.device_id,
                        device_instance_range_high_limit=self.device_id,
                        address=target_address
                    )
                else:
                    await self.app.who_is(address=LocalBroadcast())

                await asyncio.sleep(0.5)

            except Exception as err:
                _LOGGER.error("Who-Is failed: %s", err)
                return []

            # Wait for I-Am responses
            for _ in range(timeout):
                await asyncio.sleep(1)

            devices = self._collect_discovered_devices()
            _LOGGER.debug("Discovered %d BACnet devices", len(devices))
            return devices

        except Exception as err:
            _LOGGER.error("BACnet discovery failed: %s", err)
            return []
    
    
    def _collect_discovered_devices(self) -> list[dict]:
        """Collect devices from app's device info cache."""
        devices = []

        try:
            if not hasattr(self.app, 'device_info_cache'):
                _LOGGER.warning("No device_info_cache found")
                return devices

            cache = self.app.device_info_cache
            if not hasattr(cache, 'instance_cache'):
                return devices

            instance_cache = cache.instance_cache

            for device_id, device_info in instance_cache.items():
                try:
                    address = getattr(device_info, 'device_address', None)

                    if address:
                        addr_str = str(address)
                        if ':' in addr_str:
                            ip, port_str = addr_str.rsplit(':', 1)
                            port = int(port_str)
                        else:
                            ip = addr_str
                            port = 47808
                    else:
                        ip = self.host if self.host != "0.0.0.0" else "127.0.0.1"
                        port = self.port

                    name = getattr(device_info, 'device_name', None)
                    if not name:
                        name = getattr(device_info, 'objectName', f"Device {device_id}")

                    vendor = getattr(device_info, 'vendor_name', 'Unknown')

                    devices.append({
                        'device_id': int(device_id),
                        'address': ip,
                        'port': port,
                        'name': name,
                        'vendor': vendor,
                    })

                except Exception as err:
                    _LOGGER.warning("Error parsing device %s: %s", device_id, err)

        except Exception as err:
            _LOGGER.error("Error collecting discovered devices: %s", err)

        return devices
    
    
    async def get_device_name(self) -> Optional[str]:
        """Get device name."""
        try:
            if not self._connected or not self.device_id:
                return None
            
            name = await self.read_property("device", self.device_id, "objectName")
            return name
        except Exception as err:
            _LOGGER.warning("Could not read device name: %s", err)
            return None
    
    
    async def read_property(
        self, 
        object_type: str, 
        object_instance: int, 
        property_name: str
    ) -> Optional[Any]:
        """Read BACnet property."""
        if not self._connected or not self.app:
            _LOGGER.error("Not connected to BACnet network")
            return None
        
        try:
            object_id = ObjectIdentifier(f"{object_type},{object_instance}")
            device_address = Address(f"{self.host}:{self.port}")
            prop_id = PropertyIdentifier(property_name)

            try:
                result = await asyncio.wait_for(
                    self.app.read_property(
                        address=device_address,
                        objid=object_id,
                        prop=prop_id
                    ),
                    timeout=5.0
                )
                _LOGGER.debug("Read %s from %s: %s", property_name, object_id, result)
                return result
                
            except asyncio.TimeoutError:
                _LOGGER.debug("Read timed out after 5 seconds - no response from %s", device_address)
                return None
        
        except Exception as err:
            _LOGGER.error("Read failed for %s:%s.%s: %s", 
                         object_type, object_instance, property_name, err)
            import traceback
            traceback.print_exc()
            return None
    
    
    async def write_property(
        self,
        object_type: str,
        object_instance: int,
        property_name: str,
        value: Any,
        priority: int = 8
    ) -> bool:
        """Write BACnet property."""
        if not self._connected or not self.app:
            _LOGGER.error("Not connected to BACnet network")
            return False
        
        try:
            object_id = ObjectIdentifier(f"{object_type},{object_instance}")
            device_address = Address(f"{self.host}:{self.port}")
            prop_id = PropertyIdentifier(property_name)
            
            result = await self.app.write_property(
                address=device_address,
                objid=object_id,
                prop=prop_id,
                value=value,
                priority=priority
            )

            _LOGGER.debug("Wrote %s to %s:%s.%s", value, object_type, object_instance, property_name)
            return True
        
        except Exception as err:
            _LOGGER.error("Write failed for %s:%s.%s: %s", 
                         object_type, object_instance, property_name, err)
            import traceback
            traceback.print_exc()
            return False
    
    
    async def disconnect(self):
        """Disconnect from BACnet network."""
        if self.app:
            try:
                # Close link layers first to release sockets
                if hasattr(self.app, 'link_layers'):
                    for port_id, link_layer in self.app.link_layers.items():
                        try:
                            if hasattr(link_layer, 'close'):
                                if asyncio.iscoroutinefunction(link_layer.close):
                                    await link_layer.close()
                                else:
                                    link_layer.close()
                        except Exception as err:
                            _LOGGER.debug("Error closing link layer %s: %s", port_id, err)

                # Close the application
                if hasattr(self.app, 'close'):
                    close_method = self.app.close
                    if asyncio.iscoroutinefunction(close_method):
                        await close_method()
                    else:
                        close_method()
                elif hasattr(self.app, 'stop'):
                    stop_method = self.app.stop
                    if asyncio.iscoroutinefunction(stop_method):
                        await stop_method()
                    else:
                        stop_method()

                _LOGGER.debug("BACnet disconnected")

            except Exception as err:
                _LOGGER.error("Error disconnecting BACnet: %s", err)
            finally:
                self.app = None
                self._bacpypeinstance = None
                self._connected = False
        else:
            self._connected = False
    
    
    @property
    def connected(self) -> bool:
        """Return connection status."""
        return self._connected
    
    @property
    def is_connected(self) -> bool:
        """Alias for connected property (for compatibility)."""
        return self._connected
