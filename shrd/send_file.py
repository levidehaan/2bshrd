"""Send file dialog - launched from context menu."""

import sys
import asyncio
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QProgressBar, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QObject

from .config import ConfigManager, Device
from .transfer import TransferService, TransferProgress


class SendSignals(QObject):
    """Signals for send dialog."""
    progress = Signal(object)
    complete = Signal(bool, str)


class SendFileDialog(QDialog):
    """Dialog for sending a file to a device."""
    
    def __init__(self, file_path: Path, config: ConfigManager, loop: asyncio.AbstractEventLoop):
        super().__init__()
        
        self.file_path = file_path
        self.config = config
        self.loop = loop
        self.signals = SendSignals()
        self.transfer_service = TransferService(config)
        
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        """Setup the UI."""
        self.setWindowTitle("Send with 2bshrd")
        self.setMinimumWidth(400)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        
        layout = QVBoxLayout(self)
        
        # File info
        file_label = QLabel(f"<b>File:</b> {self.file_path.name}")
        layout.addWidget(file_label)
        
        size_kb = self.file_path.stat().st_size / 1024
        size_label = QLabel(f"<b>Size:</b> {size_kb:.1f} KB")
        layout.addWidget(size_label)
        
        layout.addSpacing(10)
        
        # Device selector
        device_layout = QHBoxLayout()
        device_layout.addWidget(QLabel("Send to:"))
        
        self.device_combo = QComboBox()
        devices = self.config.list_devices()
        for device in devices:
            self.device_combo.addItem(device.name, device)
        
        if not devices:
            self.device_combo.addItem("No devices - add one first")
            self.device_combo.setEnabled(False)
        
        device_layout.addWidget(self.device_combo)
        layout.addLayout(device_layout)
        
        layout.addSpacing(10)
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send_file)
        self.send_btn.setEnabled(len(devices) > 0)
        btn_layout.addWidget(self.send_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
    
    def _connect_signals(self):
        """Connect signals."""
        self.signals.progress.connect(self._on_progress)
        self.signals.complete.connect(self._on_complete)
    
    def _send_file(self):
        """Start sending the file."""
        device = self.device_combo.currentData()
        if not device:
            return
        
        self.send_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Connecting...")
        
        async def do_send():
            def progress_cb(progress: TransferProgress):
                self.signals.progress.emit(progress)
            
            try:
                success = await self.transfer_service.send_file_to_device(
                    device, self.file_path, progress_cb
                )
                self.signals.complete.emit(success, "" if success else "Transfer failed")
            except Exception as e:
                self.signals.complete.emit(False, str(e))
        
        asyncio.run_coroutine_threadsafe(do_send(), self.loop)
    
    def _on_progress(self, progress: TransferProgress):
        """Update progress."""
        self.progress_bar.setValue(int(progress.percent))
        self.status_label.setText(f"Sending: {progress.percent:.1f}%")
    
    def _on_complete(self, success: bool, error: str):
        """Handle completion."""
        if success:
            self.status_label.setText("Sent successfully!")
            QMessageBox.information(self, "Success", "File sent successfully!")
            self.accept()
        else:
            self.status_label.setText(f"Failed: {error}")
            self.send_btn.setEnabled(True)
            self.progress_bar.setVisible(False)
            QMessageBox.warning(self, "Failed", f"Failed to send file: {error}")


def main():
    """Main entry point for send dialog."""
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", required=True, help="File to send")
    args = parser.parse_args()
    
    file_path = Path(args.send)
    if not file_path.exists():
        print(f"File not found: {file_path}")
        sys.exit(1)
    
    app = QApplication(sys.argv)
    
    # Setup async loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    config = ConfigManager()
    
    dialog = SendFileDialog(file_path, config, loop)
    
    # Run the event loop in a thread
    import threading
    
    def run_loop():
        loop.run_forever()
    
    loop_thread = threading.Thread(target=run_loop, daemon=True)
    loop_thread.start()
    
    result = dialog.exec()
    
    loop.call_soon_threadsafe(loop.stop)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
