#!/usr/bin/env python3
"""
Build script for 2bshrd - creates standalone executables for Windows, Linux, and macOS.

Usage:
    python build.py              # Build for current platform
    python build.py windows      # Build for Windows
    python build.py linux        # Build for Linux  
    python build.py macos        # Build for macOS
    python build.py all          # Build for all platforms (cross-compile where possible)
"""

import subprocess
import sys
import shutil
import platform
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"

# Platform detection
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"


def ensure_pyinstaller():
    """Ensure PyInstaller is installed."""
    try:
        import PyInstaller
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)


def get_separator():
    """Get the path separator for --add-data (different on Windows vs Unix)."""
    return ";" if IS_WINDOWS else ":"


def build_windows():
    """Build Windows executable (.exe)."""
    print("\n" + "="*60)
    print("Building Windows executable...")
    print("="*60 + "\n")
    
    ensure_pyinstaller()
    sep = get_separator()
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "2bshrd",
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",
        f"--add-data=shrd{sep}shrd",
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui", 
        "--hidden-import=PySide6.QtWidgets",
        "--hidden-import=zeroconf",
        "--hidden-import=zeroconf._utils.ipaddress",
        "--hidden-import=cryptography",
        "--hidden-import=aiofiles",
        "--hidden-import=cffi",
        "--collect-all=zeroconf",
        str(ROOT / "run.py"),
    ]
    
    # Add icon if it exists
    icon_path = ROOT / "assets" / "icon.ico"
    if icon_path.exists():
        cmd.insert(-1, f"--icon={icon_path}")
    
    subprocess.run(cmd, check=True, cwd=ROOT)
    
    output = DIST / "2bshrd.exe"
    if output.exists():
        size_mb = output.stat().st_size / (1024 * 1024)
        print(f"\n✓ Windows build complete!")
        print(f"  Output: {output}")
        print(f"  Size: {size_mb:.1f} MB")
    return output


def build_linux():
    """Build Linux executable."""
    print("\n" + "="*60)
    print("Building Linux executable...")
    print("="*60 + "\n")
    
    ensure_pyinstaller()
    sep = get_separator()
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "2bshrd",
        "--onefile",
        "--noconfirm",
        "--clean",
        f"--add-data=shrd{sep}shrd",
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--hidden-import=PySide6.QtWidgets",
        "--hidden-import=zeroconf",
        "--hidden-import=zeroconf._utils.ipaddress",
        "--hidden-import=cryptography",
        "--hidden-import=aiofiles",
        "--hidden-import=cffi",
        "--collect-all=zeroconf",
        str(ROOT / "run.py"),
    ]
    
    subprocess.run(cmd, check=True, cwd=ROOT)
    
    output = DIST / "2bshrd"
    if output.exists():
        size_mb = output.stat().st_size / (1024 * 1024)
        print(f"\n✓ Linux build complete!")
        print(f"  Output: {output}")
        print(f"  Size: {size_mb:.1f} MB")
        print(f"\n  To run: chmod +x {output} && ./{output.name}")
    return output


def build_macos():
    """Build macOS application bundle (.app)."""
    print("\n" + "="*60)
    print("Building macOS application...")
    print("="*60 + "\n")
    
    ensure_pyinstaller()
    sep = get_separator()
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "2bshrd",
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",
        f"--add-data=shrd{sep}shrd",
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--hidden-import=PySide6.QtWidgets",
        "--hidden-import=zeroconf",
        "--hidden-import=zeroconf._utils.ipaddress",
        "--hidden-import=cryptography",
        "--hidden-import=aiofiles",
        "--hidden-import=cffi",
        "--collect-all=zeroconf",
        "--osx-bundle-identifier=com.2bshrd.app",
        str(ROOT / "run.py"),
    ]
    
    # Add icon if exists
    icon_path = ROOT / "assets" / "icon.icns"
    if icon_path.exists():
        cmd.insert(-1, f"--icon={icon_path}")
    
    subprocess.run(cmd, check=True, cwd=ROOT)
    
    # Check for .app bundle or standalone executable
    app_bundle = DIST / "2bshrd.app"
    standalone = DIST / "2bshrd"
    
    if app_bundle.exists():
        print(f"\n✓ macOS build complete!")
        print(f"  Output: {app_bundle}")
        print(f"\n  To install: drag to /Applications")
        return app_bundle
    elif standalone.exists():
        size_mb = standalone.stat().st_size / (1024 * 1024)
        print(f"\n✓ macOS build complete!")
        print(f"  Output: {standalone}")
        print(f"  Size: {size_mb:.1f} MB")
        return standalone


def build_current_platform():
    """Build for the current platform."""
    if IS_WINDOWS:
        return build_windows()
    elif IS_LINUX:
        return build_linux()
    elif IS_MACOS:
        return build_macos()
    else:
        print(f"Unknown platform: {sys.platform}")
        return None


def clean():
    """Clean build artifacts."""
    print("Cleaning build artifacts...")
    for path in [DIST, BUILD, ROOT / "2bshrd.spec"]:
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    print("✓ Clean complete")


def install_context_menu():
    """Install Windows context menu (requires admin)."""
    if not IS_WINDOWS:
        print("Context menu is Windows-only")
        return
    print("Installing context menu...")
    subprocess.run([sys.executable, "-m", "shrd", "--install-context-menu"], cwd=ROOT)


def print_usage():
    print(__doc__)
    print("\nCommands:")
    print("  python build.py              Build for current platform")
    print("  python build.py windows      Build Windows .exe")
    print("  python build.py linux        Build Linux executable")
    print("  python build.py macos        Build macOS app")
    print("  python build.py clean        Clean build artifacts")
    print("  python build.py context-menu Install Windows Explorer integration")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        build_current_platform()
    else:
        cmd = sys.argv[1].lower()
        
        if cmd == "windows":
            if not IS_WINDOWS:
                print("⚠ Cross-compiling to Windows from non-Windows is not supported.")
                print("  Run this script on a Windows machine.")
            else:
                build_windows()
        
        elif cmd == "linux":
            if not IS_LINUX:
                print("⚠ Cross-compiling to Linux from non-Linux is not supported.")
                print("  Run this script on a Linux machine, or use Docker:")
                print("  docker run -v $(pwd):/app python:3.11 bash -c 'cd /app && pip install -r requirements.txt pyinstaller && python build.py linux'")
            else:
                build_linux()
        
        elif cmd == "macos":
            if not IS_MACOS:
                print("⚠ Cross-compiling to macOS from non-macOS is not supported.")
                print("  Run this script on a Mac.")
            else:
                build_macos()
        
        elif cmd == "clean":
            clean()
        
        elif cmd == "context-menu":
            install_context_menu()
        
        elif cmd in ("help", "-h", "--help"):
            print_usage()
        
        else:
            print(f"Unknown command: {cmd}")
            print_usage()
