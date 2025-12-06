"""Device discovery - mDNS for LAN, background health checks, pairing codes."""

import socket
import asyncio
import hashlib
import time
from datetime import datetime
from typing import Optional, Callable, Set
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf, ServiceInfo

from .config import ConfigManager, Device, DEFAULT_PORT

SERVICE_TYPE = "_2bshrd._tcp.local."
HEALTH_CHECK_INTERVAL = 30  # seconds


class DeviceDiscovery(ServiceListener):
    """Smart device discovery - quiet, efficient, and reliable.
    
    Features:
    - mDNS auto-discovery for LAN devices (silent for known devices)
    - Background health checks for enrolled devices
    - Pairing codes for easy cross-network setup
    - Only notifies for NEW devices, silently updates known ones
    """
    
    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self.zeroconf: Optional[Zeroconf] = None
        self.browser: Optional[ServiceBrowser] = None
        self.service_info: Optional[ServiceInfo] = None
        self._health_task: Optional[asyncio.Task] = None
        self._seen_ids: Set[str] = set()  # Track already-notified devices
        
        # Callbacks - NEW device vs status update are separate
        self.on_new_device: Optional[Callable[[Device], None]] = None
        self.on_device_status: Optional[Callable[[str, bool], None]] = None  # id, online
        
        # Legacy callback for compatibility
        self.on_device_found: Optional[Callable[[Device], None]] = None
        self.on_device_lost: Optional[Callable[[str], None]] = None
    
    @property
    def pairing_code(self) -> str:
        """Generate a short pairing code for this device.
        
        Code format: XXXX-XXXX (derived from device ID + IP, changes if IP changes)
        """
        ip = self._get_local_ip()
        seed = f"{self.config.config.device_id}:{ip}:{self.config.config.port}"
        h = hashlib.sha256(seed.encode()).hexdigest()[:8].upper()
        return f"{h[:4]}-{h[4:]}"
    
    @property
    def connection_info(self) -> dict:
        """Get info needed to connect to this device."""
        return {
            "device_id": self.config.config.device_id,
            "device_name": self.config.config.device_name,
            "host": self._get_local_ip(),
            "port": self.config.config.port,
            "pairing_code": self.pairing_code
        }
    
    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Start discovery and advertising."""
        try:
            self.zeroconf = Zeroconf()
            self._register_service()
            self.browser = ServiceBrowser(self.zeroconf, SERVICE_TYPE, self)
        except Exception as e:
            print(f"mDNS discovery unavailable: {e}")
        
        # Load known device IDs to avoid re-notifying
        self._seen_ids = {d.id for d in self.config.list_devices()}
        
        # Start background health checks
        if loop:
            self._health_task = asyncio.run_coroutine_threadsafe(
                self._health_check_loop(), loop
            )
    
    def stop(self):
        """Stop discovery."""
        if self._health_task:
            self._health_task.cancel()
        
        if self.zeroconf:
            try:
                if self.service_info:
                    self.zeroconf.unregister_service(self.service_info)
                self.zeroconf.close()
            except Exception:
                pass
    
    def _register_service(self):
        """Advertise this device on the network."""
        local_ip = self._get_local_ip()
        
        self.service_info = ServiceInfo(
            SERVICE_TYPE,
            f"{self.config.config.device_name}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(local_ip)],
            port=self.config.config.port,
            properties={
                "device_id": self.config.config.device_id,
                "device_name": self.config.config.device_name,
                "pairing_code": self.pairing_code,
            },
        )
        self.zeroconf.register_service(self.service_info)
    
    def _get_local_ip(self) -> str:
        """Get the local IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    
    async def _health_check_loop(self):
        """Periodically check enrolled devices' status."""
        while True:
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
            await self._check_all_devices()
    
    async def _check_all_devices(self):
        """Check connectivity to all enrolled devices."""
        for device in self.config.list_devices():
            online = await self._ping_device(device)
            
            if online != device.is_online:
                device.is_online = online
                device.last_seen = datetime.now().isoformat() if online else device.last_seen
                self.config.update_device(device)
                
                if self.on_device_status:
                    self.on_device_status(device.id, online)
    
    async def _ping_device(self, device: Device, timeout: float = 3.0) -> bool:
        """Quick connectivity check."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(device.host, device.port),
                timeout=timeout
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False
    
    # ServiceListener callbacks (mDNS)
    
    def add_service(self, zc: Zeroconf, type_: str, name: str):
        """Called when a device is discovered on LAN."""
        info = zc.get_service_info(type_, name)
        if not info or not info.properties:
            return
        
        device_id = info.properties.get(b"device_id", b"").decode()
        device_name = info.properties.get(b"device_name", b"").decode()
        
        # Skip self
        if device_id == self.config.config.device_id:
            return
        
        addresses = info.parsed_addresses()
        if not addresses:
            return
        
        device = Device(
            id=device_id,
            name=device_name,
            host=addresses[0],
            port=info.port,
            is_online=True,
            last_seen=datetime.now().isoformat()
        )
        
        # Check if this is a NEW device or known one
        existing = self.config.get_device(device_id)
        
        if existing:
            # Known device - silently update IP/status if changed
            if existing.host != device.host or not existing.is_online:
                existing.host = device.host
                existing.is_online = True
                existing.last_seen = device.last_seen
                self.config.update_device(existing)
                
                if self.on_device_status:
                    self.on_device_status(device_id, True)
        else:
            # NEW device - notify user
            if device_id not in self._seen_ids:
                self._seen_ids.add(device_id)
                
                if self.on_new_device:
                    self.on_new_device(device)
                elif self.on_device_found:  # Legacy
                    self.on_device_found(device)
    
    def remove_service(self, zc: Zeroconf, type_: str, name: str):
        """Called when a device leaves the network."""
        # Don't immediately mark offline - could be network blip
        # Health check loop will handle actual status
        pass
    
    def update_service(self, zc: Zeroconf, type_: str, name: str):
        """Called when a device updates its info."""
        self.add_service(zc, type_, name)
