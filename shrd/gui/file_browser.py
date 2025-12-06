"""Remote file browser window."""

import asyncio
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, 
    QTreeWidgetItem, QPushButton, QLineEdit, QLabel, QProgressBar,
    QMessageBox, QHeaderView
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QIcon

from ..config import Device
from ..transfer import TransferService, TransferProgress


class BrowserSignals(QObject):
    """Signals for file browser."""
    dir_loaded = Signal(dict)
    download_progress = Signal(object)
    download_complete = Signal(str)
    error = Signal(str)


class RemoteFileBrowser(QMainWindow):
    """Window for browsing remote device files."""
    
    def __init__(
        self,
        device: Device,
        transfer_service: TransferService,
        loop: asyncio.AbstractEventLoop
    ):
        super().__init__()
        
        self.device = device
        self.transfer_service = transfer_service
        self.loop = loop
        self.signals = BrowserSignals()
        self.current_path = ""
        
        self._setup_ui()
        self._connect_signals()
        self._load_dir("")
    
    def _setup_ui(self):
        """Setup the UI."""
        self.setWindowTitle(f"Browse Files - {self.device.name}")
        self.setMinimumSize(700, 500)
        
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        
        # Navigation bar
        nav_layout = QHBoxLayout()
        
        self.back_btn = QPushButton("⬅ Back")
        self.back_btn.clicked.connect(self._go_back)
        nav_layout.addWidget(self.back_btn)
        
        self.home_btn = QPushButton("🏠 Home")
        self.home_btn.clicked.connect(lambda: self._load_dir(""))
        nav_layout.addWidget(self.home_btn)
        
        self.path_edit = QLineEdit()
        self.path_edit.returnPressed.connect(self._go_to_path)
        nav_layout.addWidget(self.path_edit)
        
        self.refresh_btn = QPushButton("🔄")
        self.refresh_btn.clicked.connect(lambda: self._load_dir(self.current_path))
        nav_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(nav_layout)
        
        # File tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Size", "Type"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.itemDoubleClicked.connect(self._item_double_clicked)
        layout.addWidget(self.tree)
        
        # Download section
        download_layout = QHBoxLayout()
        
        self.download_btn = QPushButton("📥 Download Selected")
        self.download_btn.clicked.connect(self._download_selected)
        download_layout.addWidget(self.download_btn)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        download_layout.addWidget(self.progress_bar)
        
        layout.addLayout(download_layout)
        
        # Status bar
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)
    
    def _connect_signals(self):
        """Connect signals."""
        self.signals.dir_loaded.connect(self._on_dir_loaded)
        self.signals.download_progress.connect(self._on_download_progress)
        self.signals.download_complete.connect(self._on_download_complete)
        self.signals.error.connect(self._on_error)
    
    def _load_dir(self, path: str):
        """Load directory from remote device."""
        self.status_label.setText(f"Loading {path or 'home'}...")
        self.tree.clear()
        
        async def load():
            result = await self.transfer_service.list_remote_dir(self.device, path)
            if result:
                self.signals.dir_loaded.emit(result)
            else:
                self.signals.error.emit("Failed to load directory")
        
        asyncio.run_coroutine_threadsafe(load(), self.loop)
    
    def _on_dir_loaded(self, data: dict):
        """Handle directory loaded."""
        self.current_path = data.get("path", "")
        self.parent_path = data.get("parent", "")
        self.path_edit.setText(self.current_path)
        
        self.tree.clear()
        
        for entry in data.get("entries", []):
            item = QTreeWidgetItem([
                entry["name"],
                self._format_size(entry["size"]) if not entry["is_dir"] else "",
                "Folder" if entry["is_dir"] else "File"
            ])
            item.setData(0, Qt.UserRole, entry)
            
            if entry["is_dir"]:
                item.setIcon(0, QIcon.fromTheme("folder", QIcon()))
            
            self.tree.addTopLevelItem(item)
        
        self.status_label.setText(f"{len(data.get('entries', []))} items")
    
    def _format_size(self, size: int) -> str:
        """Format file size."""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024*1024):.1f} MB"
        else:
            return f"{size / (1024*1024*1024):.1f} GB"
    
    def _go_back(self):
        """Go to parent directory."""
        if self.parent_path and self.parent_path != self.current_path:
            self._load_dir(self.parent_path)
    
    def _go_to_path(self):
        """Go to path in edit box."""
        self._load_dir(self.path_edit.text())
    
    def _item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle double-click on item."""
        entry = item.data(0, Qt.UserRole)
        if entry and entry["is_dir"]:
            self._load_dir(entry["path"])
        elif entry:
            self._download_file(entry["path"], entry["name"])
    
    def _download_selected(self):
        """Download selected file."""
        item = self.tree.currentItem()
        if not item:
            return
        
        entry = item.data(0, Qt.UserRole)
        if not entry or entry["is_dir"]:
            QMessageBox.warning(self, "Select File", "Please select a file to download")
            return
        
        self._download_file(entry["path"], entry["name"])
    
    def _download_file(self, remote_path: str, filename: str):
        """Download a file from remote."""
        self.status_label.setText(f"Downloading {filename}...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        async def download():
            def progress_cb(progress: TransferProgress):
                self.signals.download_progress.emit(progress)
            
            result = await self.transfer_service.download_from_device(
                self.device, remote_path, progress_cb
            )
            
            if result:
                self.signals.download_complete.emit(str(result))
            else:
                self.signals.error.emit("Download failed")
        
        asyncio.run_coroutine_threadsafe(download(), self.loop)
    
    def _on_download_progress(self, progress: TransferProgress):
        """Update progress bar."""
        self.progress_bar.setValue(int(progress.percent))
        self.status_label.setText(
            f"Downloading {progress.file_name}: {progress.percent:.1f}%"
        )
    
    def _on_download_complete(self, path: str):
        """Handle download complete."""
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"Downloaded to {path}")
        QMessageBox.information(self, "Download Complete", f"Saved to:\n{path}")
    
    def _on_error(self, error: str):
        """Handle error."""
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"Error: {error}")
        QMessageBox.warning(self, "Error", error)
