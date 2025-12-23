"""File transfer service - handles sending and receiving files."""

import asyncio
import ssl
import random
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Tuple, TypeVar, Any
from dataclasses import dataclass
from functools import wraps

from .config import ConfigManager, Device, CERTS_DIR, DEFAULT_PORT

# Connection retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 0.5  # seconds
RETRY_MAX_DELAY = 5.0  # seconds
CONNECTION_TIMEOUT = 10  # seconds
HANDSHAKE_TIMEOUT = 10  # seconds
from .protocol import (
    Message, MessageType, FileInfo,
    read_message, write_message, send_file, receive_file, calculate_checksum
)


@dataclass
class TransferProgress:
    """Transfer progress info."""
    file_name: str
    bytes_transferred: int
    total_bytes: int
    device_name: str
    is_upload: bool
    
    @property
    def percent(self) -> float:
        if self.total_bytes == 0:
            return 100.0
        return (self.bytes_transferred / self.total_bytes) * 100


class TransferService:
    """Manages file transfers as both client and server."""
    
    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self.server: Optional[asyncio.Server] = None
        self._running = False
        
        # Callbacks
        self.on_transfer_request: Optional[Callable[[Device, FileInfo], bool]] = None
        self.on_transfer_progress: Optional[Callable[[TransferProgress], None]] = None
        self.on_transfer_complete: Optional[Callable[[str, bool], None]] = None
        self.on_device_status_change: Optional[Callable[[str, bool], None]] = None
        self.on_connection_retry: Optional[Callable[[str, int, int], None]] = None  # device_name, attempt, max
    
    async def _connect_with_retry(
        self,
        device: Device,
        max_retries: int = MAX_RETRIES
    ) -> Optional[Tuple[asyncio.StreamReader, asyncio.StreamWriter]]:
        """Connect to a device with automatic retry and exponential backoff."""
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(device.host, device.port),
                    timeout=CONNECTION_TIMEOUT
                )
                
                # Perform handshake
                await write_message(writer, Message(MessageType.HELLO, {
                    "device_id": self.config.config.device_id,
                    "device_name": self.config.config.device_name
                }))
                
                msg = await asyncio.wait_for(read_message(reader), timeout=HANDSHAKE_TIMEOUT)
                if msg and msg.type == MessageType.HELLO_ACK:
                    return reader, writer
                
                # Handshake failed - close and retry
                writer.close()
                await writer.wait_closed()
                last_error = Exception("Handshake failed")
                
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    # Calculate delay with exponential backoff + jitter
                    delay = min(
                        RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.5),
                        RETRY_MAX_DELAY
                    )
                    print(f"Connection to {device.name} failed (attempt {attempt}/{max_retries}), retrying in {delay:.1f}s...")
                    if self.on_connection_retry:
                        self.on_connection_retry(device.name, attempt, max_retries)
                    await asyncio.sleep(delay)
        
        print(f"Failed to connect to {device.name} after {max_retries} attempts: {last_error}")
        return None
    
    async def _safe_close(self, writer: Optional[asyncio.StreamWriter]):
        """Safely close a writer connection."""
        if writer:
            try:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
            except Exception:
                pass
    
    async def start_server(self):
        """Start the transfer server."""
        self._running = True
        
        self.server = await asyncio.start_server(
            self._handle_client,
            "0.0.0.0",
            self.config.config.port
        )
        
        addr = self.server.sockets[0].getsockname()
        print(f"Transfer server listening on {addr}")
    
    async def stop_server(self):
        """Stop the transfer server."""
        self._running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
    
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming client connection."""
        peer = writer.get_extra_info("peername")
        print(f"Connection from {peer}")
        
        try:
            # Wait for HELLO
            msg = await asyncio.wait_for(read_message(reader), timeout=30)
            if not msg or msg.type != MessageType.HELLO:
                return
            
            remote_device_id = msg.payload.get("device_id")
            remote_device_name = msg.payload.get("device_name", "Unknown")
            
            # Send HELLO_ACK
            await write_message(writer, Message(MessageType.HELLO_ACK, {
                "device_id": self.config.config.device_id,
                "device_name": self.config.config.device_name
            }))
            
            # Handle messages
            while self._running:
                msg = await asyncio.wait_for(read_message(reader), timeout=300)
                if not msg:
                    break
                
                await self._process_message(msg, reader, writer, remote_device_name, peer)
                
        except asyncio.TimeoutError:
            print(f"Connection timeout from {peer}")
        except Exception as e:
            print(f"Error handling client {peer}: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
    
    async def _process_message(
        self,
        msg: Message,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        device_name: str,
        peer: tuple
    ):
        """Process incoming message."""
        
        if msg.type == MessageType.PING:
            await write_message(writer, Message(MessageType.PONG, {}))
        
        elif msg.type == MessageType.FILE_OFFER:
            await self._handle_file_offer(msg, reader, writer, device_name)
        
        elif msg.type == MessageType.LIST_DIR_REQUEST:
            await self._handle_list_dir(msg, writer)
        
        elif msg.type == MessageType.FILE_DOWNLOAD_REQUEST:
            await self._handle_download_request(msg, writer, device_name)
    
    async def _handle_file_offer(
        self,
        msg: Message,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        device_name: str
    ):
        """Handle incoming file offer."""
        file_info = FileInfo.from_dict(msg.payload["file"])
        
        # Check auto-accept or ask user
        accept = self.config.config.auto_accept
        if not accept and self.on_transfer_request:
            device = Device(id="unknown", name=device_name, host="", port=0)
            accept = self.on_transfer_request(device, file_info)
        
        if not accept:
            await write_message(writer, Message(MessageType.FILE_REJECT, {
                "reason": "User declined"
            }))
            return
        
        # Accept the file
        await write_message(writer, Message(MessageType.FILE_ACCEPT, {}))
        
        # Receive the file
        dest_dir = Path(self.config.config.downloads_dir)
        dest_path = dest_dir / file_info.name
        
        # Handle duplicate names
        counter = 1
        while dest_path.exists():
            stem = Path(file_info.name).stem
            suffix = Path(file_info.name).suffix
            dest_path = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        
        def progress_cb(received: int, total: int):
            if self.on_transfer_progress:
                self.on_transfer_progress(TransferProgress(
                    file_name=file_info.name,
                    bytes_transferred=received,
                    total_bytes=total,
                    device_name=device_name,
                    is_upload=False
                ))
        
        checksum = await receive_file(reader, dest_path, file_info.size, progress_cb)
        
        # Verify checksum
        if file_info.checksum and checksum != file_info.checksum:
            await write_message(writer, Message(MessageType.FILE_ERROR, {
                "error": "Checksum mismatch"
            }))
            dest_path.unlink()  # Delete corrupted file
            return
        
        await write_message(writer, Message(MessageType.FILE_COMPLETE, {
            "path": str(dest_path)
        }))
        
        if self.on_transfer_complete:
            self.on_transfer_complete(str(dest_path), True)
    
    async def _handle_list_dir(self, msg: Message, writer: asyncio.StreamWriter):
        """Handle directory listing request."""
        path = msg.payload.get("path", str(Path.home()))
        
        try:
            dir_path = Path(path)
            if not dir_path.exists() or not dir_path.is_dir():
                await write_message(writer, Message(MessageType.ERROR, {
                    "error": "Directory not found"
                }))
                return
            
            entries = []
            for item in sorted(dir_path.iterdir()):
                try:
                    entries.append({
                        "name": item.name,
                        "is_dir": item.is_dir(),
                        "size": item.stat().st_size if item.is_file() else 0,
                        "path": str(item)
                    })
                except PermissionError:
                    continue
            
            await write_message(writer, Message(MessageType.LIST_DIR_RESPONSE, {
                "path": str(dir_path),
                "parent": str(dir_path.parent),
                "entries": entries
            }))
            
        except Exception as e:
            await write_message(writer, Message(MessageType.ERROR, {
                "error": str(e)
            }))
    
    async def _handle_download_request(
        self,
        msg: Message,
        writer: asyncio.StreamWriter,
        device_name: str
    ):
        """Handle file download request from remote."""
        file_path = Path(msg.payload.get("path", ""))
        
        if not file_path.exists() or not file_path.is_file():
            await write_message(writer, Message(MessageType.ERROR, {
                "error": "File not found"
            }))
            return
        
        file_info = FileInfo(
            name=file_path.name,
            size=file_path.stat().st_size,
            path=str(file_path),
            checksum=calculate_checksum(file_path)
        )
        
        await write_message(writer, Message(MessageType.FILE_DOWNLOAD_START, {
            "file": file_info.to_dict()
        }))
        
        def progress_cb(sent: int, total: int):
            if self.on_transfer_progress:
                self.on_transfer_progress(TransferProgress(
                    file_name=file_info.name,
                    bytes_transferred=sent,
                    total_bytes=total,
                    device_name=device_name,
                    is_upload=True
                ))
        
        checksum = await send_file(writer, file_path, progress_cb)
    
    # Client methods
    
    async def send_file_to_device(
        self,
        device: Device,
        file_path: Path,
        progress_callback: Optional[Callable[[TransferProgress], None]] = None
    ) -> bool:
        """Send a file to a device with automatic retry."""
        conn = await self._connect_with_retry(device)
        if not conn:
            return False
        
        reader, writer = conn
        
        try:
            # Calculate checksum
            checksum = calculate_checksum(file_path)
            
            file_info = FileInfo(
                name=file_path.name,
                size=file_path.stat().st_size,
                path=str(file_path),
                checksum=checksum
            )
            
            # Offer file
            await write_message(writer, Message(MessageType.FILE_OFFER, {
                "file": file_info.to_dict()
            }))
            
            # Wait for accept/reject
            msg = await asyncio.wait_for(read_message(reader), timeout=60)
            if not msg or msg.type == MessageType.FILE_REJECT:
                print(f"File rejected: {msg.payload.get('reason', 'Unknown')}" if msg else "No response")
                return False
            
            if msg.type != MessageType.FILE_ACCEPT:
                return False
            
            # Send the file
            def progress_cb(sent: int, total: int):
                if progress_callback:
                    progress_callback(TransferProgress(
                        file_name=file_info.name,
                        bytes_transferred=sent,
                        total_bytes=total,
                        device_name=device.name,
                        is_upload=True
                    ))
            
            await send_file(writer, file_path, progress_cb)
            
            # Wait for completion
            msg = await asyncio.wait_for(read_message(reader), timeout=30)
            return msg is not None and msg.type == MessageType.FILE_COMPLETE
            
        except Exception as e:
            print(f"Error sending file to {device.name}: {e}")
            return False
        finally:
            await self._safe_close(writer)
    
    async def list_remote_dir(self, device: Device, path: str = "") -> Optional[dict]:
        """List directory on remote device with automatic retry."""
        conn = await self._connect_with_retry(device)
        if not conn:
            return None
        
        reader, writer = conn
        
        try:
            # Request directory listing
            await write_message(writer, Message(MessageType.LIST_DIR_REQUEST, {
                "path": path
            }))
            
            msg = await asyncio.wait_for(read_message(reader), timeout=30)
            
            if msg and msg.type == MessageType.LIST_DIR_RESPONSE:
                return msg.payload
            
            return None
            
        except Exception as e:
            print(f"Error listing remote dir: {e}")
            return None
        finally:
            await self._safe_close(writer)
    
    async def download_from_device(
        self,
        device: Device,
        remote_path: str,
        progress_callback: Optional[Callable[[TransferProgress], None]] = None
    ) -> Optional[Path]:
        """Download a file from remote device with automatic retry."""
        conn = await self._connect_with_retry(device)
        if not conn:
            return None
        
        reader, writer = conn
        dest_path = None
        
        try:
            # Request file
            await write_message(writer, Message(MessageType.FILE_DOWNLOAD_REQUEST, {
                "path": remote_path
            }))
            
            msg = await asyncio.wait_for(read_message(reader), timeout=30)
            if not msg or msg.type != MessageType.FILE_DOWNLOAD_START:
                return None
            
            file_info = FileInfo.from_dict(msg.payload["file"])
            
            # Receive the file
            dest_dir = Path(self.config.config.downloads_dir)
            dest_path = dest_dir / file_info.name
            
            def progress_cb(received: int, total: int):
                if progress_callback:
                    progress_callback(TransferProgress(
                        file_name=file_info.name,
                        bytes_transferred=received,
                        total_bytes=total,
                        device_name=device.name,
                        is_upload=False
                    ))
            
            checksum = await receive_file(reader, dest_path, file_info.size, progress_cb)
            
            # Verify checksum
            if file_info.checksum and checksum != file_info.checksum:
                dest_path.unlink()
                return None
            
            return dest_path
            
        except Exception as e:
            print(f"Error downloading from {device.name}: {e}")
            # Clean up partial download
            if dest_path and dest_path.exists():
                try:
                    dest_path.unlink()
                except Exception:
                    pass
            return None
        finally:
            await self._safe_close(writer)
    
    async def ping_device(self, device: Device, timeout: float = 5.0) -> bool:
        """Check if a device is online (single attempt, no retry)."""
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(device.host, device.port),
                timeout=timeout
            )
            
            await write_message(writer, Message(MessageType.HELLO, {
                "device_id": self.config.config.device_id,
                "device_name": self.config.config.device_name
            }))
            
            msg = await asyncio.wait_for(read_message(reader), timeout=timeout)
            
            return msg is not None and msg.type == MessageType.HELLO_ACK
            
        except Exception:
            return False
        finally:
            await self._safe_close(writer)
    
    async def ping_device_with_retry(self, device: Device, max_retries: int = 2) -> bool:
        """Check if a device is online with retry."""
        for attempt in range(max_retries):
            if await self.ping_device(device):
                return True
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
        return False
