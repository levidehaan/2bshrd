"""Main entry point for 2bshrd."""

import sys
import asyncio
import threading
import signal
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from .config import ConfigManager
from .gui.tray import SystemTrayApp


def run_async_loop(loop: asyncio.AbstractEventLoop):
    """Run the asyncio event loop in a separate thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


async def start_services(tray_app: SystemTrayApp, loop: asyncio.AbstractEventLoop):
    """Start all async services."""
    await tray_app.transfer_service.start_server()
    tray_app.discovery.start(loop)  # Pass loop for background health checks


def main():
    """Main application entry point."""
    # Handle command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "--send" and len(sys.argv) > 2:
            # Launch send file dialog
            from .send_file import main as send_main
            sys.argv = [sys.argv[0], "--send", sys.argv[2]]
            send_main()
            return
        elif sys.argv[1] == "--install-context-menu":
            from .shell_integration import install_context_menu
            install_context_menu()
            print("Context menu installed!")
            return
        elif sys.argv[1] == "--uninstall-context-menu":
            from .shell_integration import uninstall_context_menu
            uninstall_context_menu()
            print("Context menu uninstalled!")
            return
        elif sys.argv[1] == "--version":
            from . import __version__
            print(f"2bshrd version {__version__}")
            return
    
    # Create Qt application
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Keep running in tray
    app.setApplicationName("2bshrd")
    app.setOrganizationName("2bshrd")
    
    # Create asyncio event loop
    loop = asyncio.new_event_loop()
    
    # Start loop in background thread
    loop_thread = threading.Thread(target=run_async_loop, args=(loop,), daemon=True)
    loop_thread.start()
    
    # Create config and tray app
    config = ConfigManager()
    tray_app = SystemTrayApp(config, loop)
    tray_app.setup_tray(app)
    
    # Start services
    asyncio.run_coroutine_threadsafe(start_services(tray_app, loop), loop)
    
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\nShutting down...")
        tray_app.discovery.stop()
        loop.call_soon_threadsafe(loop.stop)
        app.quit()
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Timer to process Python signals
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(100)
    
    # Run Qt event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
