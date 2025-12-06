"""Settings window."""

from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QSpinBox, QCheckBox, QPushButton, QLabel, QFileDialog,
    QMessageBox, QGroupBox
)
from PySide6.QtCore import Qt

from ..config import ConfigManager


class SettingsWindow(QMainWindow):
    """Application settings window."""
    
    def __init__(self, config: ConfigManager):
        super().__init__()
        
        self.config = config
        self._setup_ui()
        self._load_settings()
    
    def _setup_ui(self):
        """Setup the UI."""
        self.setWindowTitle("2bshrd Settings")
        self.setMinimumSize(450, 400)
        
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        
        # Device Info
        device_group = QGroupBox("This Device")
        device_layout = QFormLayout()
        
        self.device_name_edit = QLineEdit()
        device_layout.addRow("Device Name:", self.device_name_edit)
        
        self.device_id_label = QLabel()
        self.device_id_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        device_layout.addRow("Device ID:", self.device_id_label)
        
        device_group.setLayout(device_layout)
        layout.addWidget(device_group)
        
        # Network
        network_group = QGroupBox("Network")
        network_layout = QFormLayout()
        
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        network_layout.addRow("Port:", self.port_spin)
        
        network_group.setLayout(network_layout)
        layout.addWidget(network_group)
        
        # Transfers
        transfer_group = QGroupBox("Transfers")
        transfer_layout = QFormLayout()
        
        downloads_layout = QHBoxLayout()
        self.downloads_edit = QLineEdit()
        self.downloads_edit.setReadOnly(True)
        downloads_layout.addWidget(self.downloads_edit)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_downloads)
        downloads_layout.addWidget(browse_btn)
        
        transfer_layout.addRow("Downloads Folder:", downloads_layout)
        
        self.auto_accept_check = QCheckBox("Auto-accept incoming files")
        transfer_layout.addRow("", self.auto_accept_check)
        
        transfer_group.setLayout(transfer_layout)
        layout.addWidget(transfer_group)
        
        # Context Menu
        context_group = QGroupBox("Windows Explorer Integration")
        context_layout = QVBoxLayout()
        
        context_info = QLabel("Add 'Send to 2bshrd' to right-click menu in Explorer")
        context_layout.addWidget(context_info)
        
        context_btns = QHBoxLayout()
        
        self.install_context_btn = QPushButton("Install Context Menu")
        self.install_context_btn.clicked.connect(self._install_context_menu)
        context_btns.addWidget(self.install_context_btn)
        
        self.uninstall_context_btn = QPushButton("Remove Context Menu")
        self.uninstall_context_btn.clicked.connect(self._uninstall_context_menu)
        context_btns.addWidget(self.uninstall_context_btn)
        
        context_layout.addLayout(context_btns)
        context_group.setLayout(context_layout)
        layout.addWidget(context_group)
        
        layout.addStretch()
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save_settings)
        btn_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.close)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
    
    def _load_settings(self):
        """Load current settings into UI."""
        cfg = self.config.config
        
        self.device_name_edit.setText(cfg.device_name)
        self.device_id_label.setText(cfg.device_id[:16] + "...")
        self.port_spin.setValue(cfg.port)
        self.downloads_edit.setText(cfg.downloads_dir)
        self.auto_accept_check.setChecked(cfg.auto_accept)
    
    def _save_settings(self):
        """Save settings."""
        cfg = self.config.config
        
        cfg.device_name = self.device_name_edit.text()
        cfg.port = self.port_spin.value()
        cfg.downloads_dir = self.downloads_edit.text()
        cfg.auto_accept = self.auto_accept_check.isChecked()
        
        self.config.save_config()
        
        QMessageBox.information(
            self, "Settings Saved",
            "Settings saved. Restart the app for port changes to take effect."
        )
        self.close()
    
    def _browse_downloads(self):
        """Browse for downloads folder."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Downloads Folder",
            self.downloads_edit.text()
        )
        if folder:
            self.downloads_edit.setText(folder)
    
    def _install_context_menu(self):
        """Install Windows context menu."""
        from ..shell_integration import install_context_menu
        
        try:
            install_context_menu()
            QMessageBox.information(
                self, "Success",
                "Context menu installed! Right-click any file in Explorer to use."
            )
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to install: {e}")
    
    def _uninstall_context_menu(self):
        """Uninstall Windows context menu."""
        from ..shell_integration import uninstall_context_menu
        
        try:
            uninstall_context_menu()
            QMessageBox.information(self, "Success", "Context menu removed.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to uninstall: {e}")
