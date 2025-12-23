"""Device discovery - mDNS for LAN, background health checks, pairing codes."""

import socket
import asyncio
import hashlib
import time
import random
from datetime import datetime
from typing import Optional, Callable, Set, Dict
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf, ServiceInfo

from .config import ConfigManager, Device, DEFAULT_PORT

SERVICE_TYPE = "_2bshrd._tcp.local."

# Health check configuration
HEALTH_CHECK_INTERVAL = 10  # seconds - faster checks for quicker recovery
HEALTH_CHECK_INTERVAL_OFFLINE = 5  # seconds - even faster for offline devices
INITIAL_HEALTH_CHECK_DELAY = 2  # seconds - quick check on startup
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_BASE_DELAY = 1.0  # seconds
RECONNECT_MAX_DELAY = 30.0  # seconds
PING_TIMEOUT = 3.0  # seconds
PING_RETRIES = 2  # retry pings before marking offline


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
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Connection stability tracking
        self._reconnect_attempts: Dict[str, int] = {}  # device_id -> attempt count
        self._consecutive_failures: Dict[str, int] = {}  # device_id -> failure count
        self._pending_reconnects: Set[str] = set()  # devices currently reconnecting
        
        # Callbacks - NEW device vs status update are separate
        self.on_new_device: Optional[Callable[[Device], None]] = None
        self.on_device_status: Optional[Callable[[str, bool], None]] = None  # id, online
        self.on_reconnect_attempt: Optional[Callable[[str, int], None]] = None  # id, attempt
        
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
        self._loop = loop
        
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
            # Also run an immediate check after a short delay
            asyncio.run_coroutine_threadsafe(
                self._initial_health_check(), loop
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
    
    async def _initial_health_check(self):
        """Run a quick health check shortly after startup."""
        await asyncio.sleep(INITIAL_HEALTH_CHECK_DELAY)
        print("Running initial device health check...")
        await self._check_all_devices()
    
    async def _health_check_loop(self):
        """Periodically check enrolled devices' status with adaptive intervals."""
        while True:
            # Check if any devices are offline - use faster interval if so
            has_offline = any(not d.is_online for d in self.config.list_devices())
            interval = HEALTH_CHECK_INTERVAL_OFFLINE if has_offline else HEALTH_CHECK_INTERVAL
            
            await asyncio.sleep(interval)
            await self._check_all_devices()
    
    async def _check_all_devices(self):
        """Check connectivity to all enrolled devices concurrently."""
        devices = self.config.list_devices()
        if not devices:
            return
        
        # Check all devices concurrently for faster status updates
        tasks = [self._check_device_with_retry(device) for device in devices]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _check_device_with_retry(self, device: Device):
        """Check a single device with retry logic."""
        # Try multiple pings before declaring offline
        online = False
        for attempt in range(PING_RETRIES):
            online = await self._ping_device(device)
            if online:
                break
            if attempt < PING_RETRIES - 1:
                await asyncio.sleep(0.5)  # Brief pause between retries
        
        was_online = device.is_online
        
        if online:
            # Device is online - reset failure counters
            self._consecutive_failures[device.id] = 0
            self._reconnect_attempts[device.id] = 0
            self._pending_reconnects.discard(device.id)
            
            if not was_online:
                device.is_online = True
                device.last_seen = datetime.now().isoformat()
                self.config.update_device(device)
                print(f"Device {device.name} is back online")
                if self.on_device_status:
                    self.on_device_status(device.id, True)
        else:
            # Device appears offline
            self._consecutive_failures[device.id] = self._consecutive_failures.get(device.id, 0) + 1
            
            # Only mark offline after multiple consecutive failures
            if self._consecutive_failures[device.id] >= 2 and was_online:
                device.is_online = False
                self.config.update_device(device)
                print(f"Device {device.name} went offline")
                if self.on_device_status:
                    self.on_device_status(device.id, False)
                
                # Schedule reconnection attempts
                if device.id not in self._pending_reconnects:
                    self._schedule_reconnect(device)
    
    def _schedule_reconnect(self, device: Device):
        """Schedule automatic reconnection attempts with exponential backoff."""
        if not self._loop or device.id in self._pending_reconnects:
            return
        
        self._pending_reconnects.add(device.id)
        asyncio.run_coroutine_threadsafe(
            self._reconnect_with_backoff(device), self._loop
        )
    
    async def _reconnect_with_backoff(self, device: Device):
        """Attempt to reconnect to a device with exponential backoff."""
        attempt = 0
        
        while attempt < MAX_RECONNECT_ATTEMPTS:
            attempt += 1
            self._reconnect_attempts[device.id] = attempt
            
            # Calculate delay with exponential backoff + jitter
            delay = min(
                RECONNECT_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1),
                RECONNECT_MAX_DELAY
            )
            
            print(f"Reconnect attempt {attempt}/{MAX_RECONNECT_ATTEMPTS} for {device.name} in {delay:.1f}s")
            if self.on_reconnect_attempt:
                self.on_reconnect_attempt(device.id, attempt)
            
            await asyncio.sleep(delay)
            
            # Try to connect
            online = await self._ping_device(device)
            
            if online:
                device.is_online = True
                device.last_seen = datetime.now().isoformat()
                self.config.update_device(device)
                self._consecutive_failures[device.id] = 0
                self._reconnect_attempts[device.id] = 0
                self._pending_reconnects.discard(device.id)
                print(f"Successfully reconnected to {device.name}")
                if self.on_device_status:
                    self.on_device_status(device.id, True)
                return
        
        print(f"Failed to reconnect to {device.name} after {MAX_RECONNECT_ATTEMPTS} attempts")
        self._pending_reconnects.discard(device.id)
    
    async def force_reconnect(self, device_id: str):
        """Force an immediate reconnection attempt for a specific device."""
        device = self.config.get_device(device_id)
        if not device:
            return False
        
        # Reset counters and try immediately
        self._consecutive_failures[device_id] = 0
        self._reconnect_attempts[device_id] = 0
        self._pending_reconnects.discard(device_id)
        
        online = await self._ping_device(device)
        if online:
            device.is_online = True
            device.last_seen = datetime.now().isoformat()
            self.config.update_device(device)
            if self.on_device_status:
                self.on_device_status(device_id, True)
        return online
    
    async def _ping_device(self, device: Device, timeout: float = PING_TIMEOUT) -> bool:
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
        # Extract device info from service name if possible
        # Schedule an immediate health check for this device
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self._handle_service_removal(name), self._loop
            )
    
    async def _handle_service_removal(self, service_name: str):
        """Handle mDNS service removal - verify device status."""
        # Brief delay to avoid reacting to network blips
        await asyncio.sleep(1.0)
        
        # Check all devices since we can't reliably get device_id from service name
        for device in self.config.list_devices():
            if device.name in service_name:
                # This device's service was removed - verify it's actually offline
                online = await self._ping_device(device, timeout=2.0)
                if not online:
                    # Confirm with a retry
                    await asyncio.sleep(0.5)
                    online = await self._ping_device(device, timeout=2.0)
                
                if not online and device.is_online:
                    self._consecutive_failures[device.id] = 2  # Fast-track to offline
                    device.is_online = False
                    self.config.update_device(device)
                    print(f"Device {device.name} disconnected (mDNS removal)")
                    if self.on_device_status:
                        self.on_device_status(device.id, False)
                    self._schedule_reconnect(device)
                break
    
    def update_service(self, zc: Zeroconf, type_: str, name: str):
        """Called when a device updates its info."""
        self.add_service(zc, type_, name)
