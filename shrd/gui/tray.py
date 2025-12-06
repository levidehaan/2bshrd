"""System tray application."""

import sys
import asyncio
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget, QMessageBox,
    QInputDialog, QFileDialog
)
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QFont
from PySide6.QtCore import QObject, Signal, Slot, QTimer

from ..config import ConfigManager, Device
from ..transfer import TransferService, TransferProgress
from ..discovery import DeviceDiscovery


def create_default_icon() -> QIcon:
    """Create a simple default icon."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    
    # Draw a share icon (two circles with arrow)
    painter.setBrush(QColor(52, 152, 219))  # Blue
    painter.setPen(QColor(41, 128, 185))
    
    # Main circle
    painter.drawEllipse(8, 8, 48, 48)
    
    # Arrow
    painter.setPen(QColor(255, 255, 255))
    painter.setFont(QFont("Arial", 24, QFont.Bold))
    painter.drawText(pixmap.rect(), 0x84, "⇄")  # Center
    
    painter.end()
    return QIcon(pixmap)


class TraySignals(QObject):
    """Signals for cross-thread communication."""
    transfer_request = Signal(object, object)  # Device, FileInfo
    transfer_progress = Signal(object)  # TransferProgress
    transfer_complete = Signal(str, bool)  # path, success
    device_found = Signal(object)  # Device
    device_status = Signal(str, bool)  # device_id, online
    show_notification = Signal(str, str)  # title, message


class SystemTrayApp(QObject):
    """Main system tray application."""
    
    def __init__(self, config: ConfigManager, loop: asyncio.AbstractEventLoop):
        super().__init__()
        
        self.config = config
        self.loop = loop
        self.signals = TraySignals()
        
        # Services
        self.transfer_service = TransferService(config)
        self.discovery = DeviceDiscovery(config)
        
        # Setup callbacks
        self._setup_callbacks()
        
        # GUI
        self.app: Optional[QApplication] = None
        self.tray: Optional[QSystemTrayIcon] = None
        self.device_menu: Optional[QMenu] = None
        
        # Windows
        self.file_browser_window = None
        self.settings_window = None
        
        # Connect signals
        self.signals.transfer_request.connect(self._on_transfer_request)
        self.signals.transfer_complete.connect(self._on_transfer_complete)
        self.signals.device_found.connect(self._on_device_found)
        self.signals.device_status.connect(self._on_device_status)
        self.signals.show_notification.connect(self._show_notification)
    
    def _setup_callbacks(self):
        """Setup service callbacks."""
        def on_transfer_request(device: Device, file_info) -> bool:
            # This runs in async context, need to use signal
            # For now, auto-accept (we'll add proper dialog later)
            return True
        
        def on_progress(progress: TransferProgress):
            self.signals.transfer_progress.emit(progress)
        
        def on_complete(path: str, success: bool):
            self.signals.transfer_complete.emit(path, success)
        
        def on_new_device(device: Device):
            # Only called for NEW devices, not known ones
            self.signals.device_found.emit(device)
        
        def on_device_status(device_id: str, online: bool):
            self.signals.device_status.emit(device_id, online)
        
        self.transfer_service.on_transfer_request = on_transfer_request
        self.transfer_service.on_transfer_progress = on_progress
        self.transfer_service.on_transfer_complete = on_complete
        self.discovery.on_new_device = on_new_device
        self.discovery.on_device_status = on_device_status
    
    def setup_tray(self, app: QApplication):
        """Setup the system tray icon and menu."""
        self.app = app
        
        # Create tray icon
        self.tray = QSystemTrayIcon(create_default_icon(), app)
        self.tray.setToolTip(f"2bshrd - {self.config.config.device_name}")
        
        # Create menu
        menu = QMenu()
        
        # This device info
        this_device_menu = menu.addMenu(f"💻 {self.config.config.device_name}")
        
        code_action = QAction(f"Pairing Code: {self.discovery.pairing_code}", this_device_menu)
        code_action.triggered.connect(self._copy_pairing_code)
        this_device_menu.addAction(code_action)
        
        ip_action = QAction(f"IP: {self.discovery._get_local_ip()}:{self.config.config.port}", this_device_menu)
        ip_action.setEnabled(False)
        this_device_menu.addAction(ip_action)
        
        menu.addSeparator()
        
        # Device submenu
        self.device_menu = menu.addMenu("📱 Devices")
        self._rebuild_device_menu()
        
        menu.addSeparator()
        
        # Actions
        add_device_action = QAction("➕ Add Device...", menu)
        add_device_action.triggered.connect(self._add_device_dialog)
        menu.addAction(add_device_action)
        
        send_file_action = QAction("📤 Send File...", menu)
        send_file_action.triggered.connect(self._send_file_dialog)
        menu.addAction(send_file_action)
        
        menu.addSeparator()
        
        settings_action = QAction("⚙️ Settings", menu)
        settings_action.triggered.connect(self._show_settings)
        menu.addAction(settings_action)
        
        open_downloads = QAction("📁 Open Downloads", menu)
        open_downloads.triggered.connect(self._open_downloads)
        menu.addAction(open_downloads)
        
        menu.addSeparator()
        
        quit_action = QAction("❌ Quit", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)
        
        self.tray.setContextMenu(menu)
        self.tray.show()
        
        # Show startup notification
        self.tray.showMessage(
            "2bshrd Running",
            f"Listening on port {self.config.config.port}",
            QSystemTrayIcon.Information,
            2000
        )
    
    def _rebuild_device_menu(self):
        """Rebuild the device submenu."""
        self.device_menu.clear()
        
        devices = self.config.list_devices()
        
        if not devices:
            no_devices = QAction("No devices enrolled", self.device_menu)
            no_devices.setEnabled(False)
            self.device_menu.addAction(no_devices)
            return
        
        for device in devices:
            device_submenu = self.device_menu.addMenu(
                f"{'🟢' if device.is_online else '⚫'} {device.name}"
            )
            
            # Send file to device
            send_action = QAction("📤 Send File...", device_submenu)
            send_action.triggered.connect(lambda checked, d=device: self._send_to_device(d))
            device_submenu.addAction(send_action)
            
            # Browse remote files
            browse_action = QAction("📁 Browse Files...", device_submenu)
            browse_action.triggered.connect(lambda checked, d=device: self._browse_device(d))
            device_submenu.addAction(browse_action)
            
            # Ping device
            ping_action = QAction("🔍 Check Status", device_submenu)
            ping_action.triggered.connect(lambda checked, d=device: self._ping_device(d))
            device_submenu.addAction(ping_action)
            
            device_submenu.addSeparator()
            
            # Remove device
            remove_action = QAction("🗑️ Remove", device_submenu)
            remove_action.triggered.connect(lambda checked, d=device: self._remove_device(d))
            device_submenu.addAction(remove_action)
    
    @Slot()
    def _add_device_dialog(self):
        """Show dialog to add a new device."""
        name, ok = QInputDialog.getText(None, "Add Device", "Device Name:")
        if not ok or not name:
            return
        
        host, ok = QInputDialog.getText(None, "Add Device", "IP Address or Hostname:")
        if not ok or not host:
            return
        
        port, ok = QInputDialog.getInt(None, "Add Device", "Port:", 52637, 1, 65535)
        if not ok:
            return
        
        import uuid
        device = Device(
            id=str(uuid.uuid4()),
            name=name,
            host=host,
            port=port
        )
        
        self.config.add_device(device)
        self._rebuild_device_menu()
        
        self.tray.showMessage("Device Added", f"{name} added successfully", QSystemTrayIcon.Information, 2000)
    
    def _send_to_device(self, device: Device):
        """Open file dialog and send to device."""
        file_path, _ = QFileDialog.getOpenFileName(None, f"Send to {device.name}")
        if not file_path:
            return
        
        # Run async send
        asyncio.run_coroutine_threadsafe(
            self._async_send_file(device, Path(file_path)),
            self.loop
        )
    
    async def _async_send_file(self, device: Device, file_path: Path):
        """Async file send."""
        self.signals.show_notification.emit("Sending", f"Sending {file_path.name} to {device.name}...")
        
        success = await self.transfer_service.send_file_to_device(device, file_path)
        
        if success:
            self.signals.show_notification.emit("Sent", f"{file_path.name} sent successfully")
        else:
            self.signals.show_notification.emit("Failed", f"Failed to send {file_path.name}")
    
    def _browse_device(self, device: Device):
        """Open remote file browser for device."""
        from .file_browser import RemoteFileBrowser
        
        self.file_browser_window = RemoteFileBrowser(device, self.transfer_service, self.loop)
        self.file_browser_window.show()
    
    def _ping_device(self, device: Device):
        """Ping a device to check status."""
        async def do_ping():
            online = await self.transfer_service.ping_device(device)
            device.is_online = online
            self.config.update_device(device)
            
            status = "online" if online else "offline"
            self.signals.show_notification.emit("Status", f"{device.name} is {status}")
        
        asyncio.run_coroutine_threadsafe(do_ping(), self.loop)
        self._rebuild_device_menu()
    
    def _remove_device(self, device: Device):
        """Remove a device."""
        reply = QMessageBox.question(
            None, "Remove Device",
            f"Remove {device.name}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.config.remove_device(device.id)
            self._rebuild_device_menu()
    
    @Slot()
    def _send_file_dialog(self):
        """Show dialog to select device and file."""
        devices = self.config.list_devices()
        if not devices:
            QMessageBox.warning(None, "No Devices", "Add a device first")
            return
        
        # Select device
        device_names = [d.name for d in devices]
        name, ok = QInputDialog.getItem(None, "Send File", "Select device:", device_names, 0, False)
        if not ok:
            return
        
        device = next(d for d in devices if d.name == name)
        self._send_to_device(device)
    
    @Slot()
    def _show_settings(self):
        """Show settings window."""
        from .settings import SettingsWindow
        self.settings_window = SettingsWindow(self.config)
        self.settings_window.show()
    
    @Slot()
    def _open_downloads(self):
        """Open downloads folder."""
        import subprocess
        downloads = Path(self.config.config.downloads_dir)
        downloads.mkdir(parents=True, exist_ok=True)
        
        if sys.platform == "win32":
            subprocess.run(["explorer", str(downloads)])
        else:
            subprocess.run(["xdg-open", str(downloads)])
    
    @Slot()
    def _quit(self):
        """Quit the application."""
        self.discovery.stop()
        if self.tray:
            self.tray.hide()
        QApplication.quit()
    
    @Slot(object, object)
    def _on_transfer_request(self, device: Device, file_info):
        """Handle incoming transfer request."""
        reply = QMessageBox.question(
            None, "Incoming File",
            f"{device.name} wants to send:\n{file_info.name} ({file_info.size // 1024} KB)\n\nAccept?",
            QMessageBox.Yes | QMessageBox.No
        )
        return reply == QMessageBox.Yes
    
    @Slot(str, bool)
    def _on_transfer_complete(self, path: str, success: bool):
        """Handle transfer completion."""
        if success:
            self.tray.showMessage(
                "File Received",
                f"Saved to {path}",
                QSystemTrayIcon.Information,
                3000
            )
    
    @Slot(object)
    def _on_device_found(self, device: Device):
        """Handle discovered device."""
        existing = self.config.get_device(device.id)
        if not existing:
            # Auto-add discovered devices (could make this a setting)
            self.config.add_device(device)
            self._rebuild_device_menu()
            
            self.tray.showMessage(
                "Device Found",
                f"Discovered {device.name}",
                QSystemTrayIcon.Information,
                2000
            )
        else:
            # Update status
            existing.is_online = True
            existing.host = device.host  # IP may have changed
            self.config.update_device(existing)
            self._rebuild_device_menu()
    
    @Slot(str, bool)
    def _on_device_status(self, device_id: str, online: bool):
        """Handle device status change (silent, just refresh menu)."""
        self._rebuild_device_menu()
    
    @Slot()
    def _copy_pairing_code(self):
        """Copy pairing code to clipboard."""
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self.discovery.pairing_code)
        self.tray.showMessage(
            "Copied",
            f"Pairing code copied: {self.discovery.pairing_code}",
            QSystemTrayIcon.Information,
            1500
        )
    
    @Slot(str, str)
    def _show_notification(self, title: str, message: str):
        """Show a tray notification."""
        if self.tray:
            self.tray.showMessage(title, message, QSystemTrayIcon.Information, 3000)
