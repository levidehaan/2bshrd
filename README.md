# 2bshrd - Cross-Platform File Sharing

Seamless peer-to-peer file sharing for Windows, Linux, and macOS:

- 🖱️ **Right-click "Send to Device"** in Windows Explorer
- 📁 **System tray app** with device management
- 🔍 **Remote file browser** - browse & download from other machines
- 🔄 **Auto-discovery** - devices on same LAN find each other
- 🔒 **Encrypted transfers** over TCP

## Quick Start

### Option 1: Download Pre-built Executable (Windows)

1. Download `2bshrd.exe` from Releases
2. Run it - appears in system tray
3. Done! No Python needed

### Option 2: Run from Source

```bash
# Install dependencies
pip install -r requirements.txt

# Run
python -m shrd
```

### Option 3: Using UV (Linux/macOS)

```bash
uv pip install -r requirements.txt
uv run python -m shrd
```

## Usage

1. **Run on each machine** you want to share files between
2. **Same network?** Devices auto-discover each other
3. **Different network?** Click tray → Add Device → Enter IP
4. **Send files:** Right-click file → Send with 2bshrd (Windows) or use tray menu

## Building Executables

### Windows
```powershell
python build.py windows
# Output: dist/2bshrd.exe (54 MB standalone, no Python needed)
```

### Linux
```bash
python build.py linux
# Output: dist/2bshrd (standalone executable)
```

### macOS
```bash
python build.py macos
# Output: dist/2bshrd.app (application bundle)
```

### Build for Linux from Windows (via Docker)
```bash
docker run -v ${PWD}:/app -w /app python:3.11 bash -c "pip install -r requirements.txt pyinstaller && python build.py linux"
```

## Architecture

```
┌─────────────────┐         TCP/52637         ┌─────────────────┐
│   Windows PC    │◄─────────────────────────►│   Linux Server  │
│  (2bshrd.exe)   │    Auto-discovery (mDNS)  │   (./2bshrd)    │
└─────────────────┘                           └─────────────────┘
        ▲                                              ▲
        │              ┌─────────────────┐             │
        └──────────────│    MacBook      │─────────────┘
                       │ (2bshrd.app)    │
                       └─────────────────┘
```

- **Peer-to-peer** - No cloud server, direct device-to-device
- **mDNS discovery** - Auto-finds devices on same LAN
- **Background health checks** - Tracks which devices are online
- **Protocol**: JSON headers + binary file chunks over TCP
