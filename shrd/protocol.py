"""Network protocol for file transfers."""

import json
import struct
import asyncio
import hashlib
from enum import IntEnum
from dataclasses import dataclass, asdict
from typing import Optional, Callable, Any
from pathlib import Path

# Protocol: [4-byte header length][JSON header][payload]

PROTOCOL_VERSION = 1
CHUNK_SIZE = 64 * 1024  # 64KB chunks


class MessageType(IntEnum):
    """Protocol message types."""
    # Handshake
    HELLO = 1
    HELLO_ACK = 2
    
    # File transfer
    FILE_OFFER = 10
    FILE_ACCEPT = 11
    FILE_REJECT = 12
    FILE_CHUNK = 13
    FILE_COMPLETE = 14
    FILE_ERROR = 15
    
    # Remote file browser
    LIST_DIR_REQUEST = 20
    LIST_DIR_RESPONSE = 21
    FILE_DOWNLOAD_REQUEST = 22
    FILE_DOWNLOAD_START = 23
    
    # Status
    PING = 30
    PONG = 31
    
    # Errors
    ERROR = 99


@dataclass
class Message:
    """Protocol message."""
    type: MessageType
    payload: dict
    
    def to_bytes(self) -> bytes:
        header = json.dumps({
            "version": PROTOCOL_VERSION,
            "type": self.type,
            "payload": self.payload
        }).encode("utf-8")
        return struct.pack(">I", len(header)) + header
    
    @classmethod
    def from_bytes(cls, data: bytes) -> "Message":
        header = json.loads(data.decode("utf-8"))
        return cls(
            type=MessageType(header["type"]),
            payload=header.get("payload", {})
        )


@dataclass
class FileInfo:
    """File metadata."""
    name: str
    size: int
    path: str
    checksum: Optional[str] = None
    is_dir: bool = False
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "FileInfo":
        return cls(**data)


async def read_message(reader: asyncio.StreamReader) -> Optional[Message]:
    """Read a message from the stream."""
    try:
        header_len_data = await reader.readexactly(4)
        header_len = struct.unpack(">I", header_len_data)[0]
        
        if header_len > 10 * 1024 * 1024:  # 10MB header limit
            raise ValueError("Header too large")
        
        header_data = await reader.readexactly(header_len)
        return Message.from_bytes(header_data)
    except asyncio.IncompleteReadError:
        return None
    except Exception as e:
        raise


async def write_message(writer: asyncio.StreamWriter, message: Message):
    """Write a message to the stream."""
    writer.write(message.to_bytes())
    await writer.drain()


async def send_file(
    writer: asyncio.StreamWriter,
    file_path: Path,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> str:
    """Send a file over the connection. Returns checksum."""
    file_size = file_path.stat().st_size
    sent = 0
    hasher = hashlib.sha256()
    
    with open(file_path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            hasher.update(chunk)
            
            # Send chunk message
            msg = Message(MessageType.FILE_CHUNK, {"size": len(chunk)})
            writer.write(msg.to_bytes())
            writer.write(chunk)
            await writer.drain()
            
            sent += len(chunk)
            if progress_callback:
                progress_callback(sent, file_size)
    
    return hasher.hexdigest()


async def receive_file(
    reader: asyncio.StreamReader,
    dest_path: Path,
    expected_size: int,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> str:
    """Receive a file from the connection. Returns checksum."""
    received = 0
    hasher = hashlib.sha256()
    
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(dest_path, "wb") as f:
        while received < expected_size:
            msg = await read_message(reader)
            if not msg or msg.type != MessageType.FILE_CHUNK:
                raise ValueError(f"Expected FILE_CHUNK, got {msg.type if msg else 'None'}")
            
            chunk_size = msg.payload["size"]
            chunk = await reader.readexactly(chunk_size)
            
            hasher.update(chunk)
            f.write(chunk)
            
            received += chunk_size
            if progress_callback:
                progress_callback(received, expected_size)
    
    return hasher.hexdigest()


def calculate_checksum(file_path: Path) -> str:
    """Calculate SHA-256 checksum of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()
