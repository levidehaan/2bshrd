"""Configuration and device management."""

import json
import uuid
import socket
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional
from cryptography.fernet import Fernet

# Default paths
if __import__("sys").platform == "win32":
    CONFIG_DIR = Path.home() / "AppData" / "Local" / "2bshrd"
else:
    CONFIG_DIR = Path.home() / ".config" / "2bshrd"

CONFIG_FILE = CONFIG_DIR / "config.json"
DEVICES_FILE = CONFIG_DIR / "devices.json"
CERTS_DIR = CONFIG_DIR / "certs"
DOWNLOADS_DIR = Path.home() / "Downloads" / "2bshrd"

DEFAULT_PORT = 52637


@dataclass
class Device:
    """Represents an enrolled device."""
    id: str
    name: str
    host: str
    port: int = DEFAULT_PORT
    last_seen: Optional[str] = None
    is_online: bool = False
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "Device":
        return cls(**data)


@dataclass
class AppConfig:
    """Application configuration."""
    device_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    device_name: str = field(default_factory=socket.gethostname)
    port: int = DEFAULT_PORT
    downloads_dir: str = field(default_factory=lambda: str(DOWNLOADS_DIR))
    auto_accept: bool = False
    encryption_key: str = field(default_factory=lambda: Fernet.generate_key().decode())
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        return cls(**data)


class ConfigManager:
    """Manages app configuration and enrolled devices."""
    
    def __init__(self):
        self._ensure_dirs()
        self.config = self._load_config()
        self.devices: dict[str, Device] = self._load_devices()
    
    def _ensure_dirs(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CERTS_DIR.mkdir(parents=True, exist_ok=True)
        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    
    def _load_config(self) -> AppConfig:
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text())
                return AppConfig.from_dict(data)
            except Exception:
                pass
        config = AppConfig()
        self.save_config(config)
        return config
    
    def save_config(self, config: Optional[AppConfig] = None):
        if config:
            self.config = config
        CONFIG_FILE.write_text(json.dumps(self.config.to_dict(), indent=2))
    
    def _load_devices(self) -> dict[str, Device]:
        if DEVICES_FILE.exists():
            try:
                data = json.loads(DEVICES_FILE.read_text())
                return {d["id"]: Device.from_dict(d) for d in data}
            except Exception:
                pass
        return {}
    
    def save_devices(self):
        data = [d.to_dict() for d in self.devices.values()]
        DEVICES_FILE.write_text(json.dumps(data, indent=2))
    
    def add_device(self, device: Device):
        self.devices[device.id] = device
        self.save_devices()
    
    def remove_device(self, device_id: str):
        if device_id in self.devices:
            del self.devices[device_id]
            self.save_devices()
    
    def update_device(self, device: Device):
        self.devices[device.id] = device
        self.save_devices()
    
    def get_device(self, device_id: str) -> Optional[Device]:
        return self.devices.get(device_id)
    
    def list_devices(self) -> list[Device]:
        return list(self.devices.values())
