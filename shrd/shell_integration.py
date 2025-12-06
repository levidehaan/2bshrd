"""Windows shell integration - context menu for Explorer."""

import sys
import os
import winreg
from pathlib import Path

# Registry paths for context menu
CONTEXT_MENU_KEY = r"*\shell\2bshrd"
CONTEXT_MENU_COMMAND_KEY = r"*\shell\2bshrd\command"


def get_exe_path() -> str:
    """Get the path to the executable or script."""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return sys.executable
    else:
        # Running as script - use pythonw to avoid console
        python_path = sys.executable.replace("python.exe", "pythonw.exe")
        script_path = Path(__file__).parent.parent / "shrd" / "send_file.py"
        return f'"{python_path}" "{script_path}"'


def install_context_menu():
    """Install the right-click context menu in Windows Explorer.
    
    Requires admin privileges to write to HKEY_CLASSES_ROOT.
    Falls back to HKEY_CURRENT_USER for per-user installation.
    """
    exe_path = get_exe_path()
    
    # Try HKEY_CLASSES_ROOT first (requires admin), fall back to HKEY_CURRENT_USER
    try:
        _install_to_registry(winreg.HKEY_CLASSES_ROOT, exe_path)
    except PermissionError:
        # Fall back to per-user installation
        user_key = r"Software\Classes\*\shell\2bshrd"
        user_command_key = r"Software\Classes\*\shell\2bshrd\command"
        
        # Create main key
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, user_key)
        winreg.SetValue(key, "", winreg.REG_SZ, "Send with 2bshrd")
        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, "")
        winreg.CloseKey(key)
        
        # Create command key
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, user_command_key)
        winreg.SetValue(key, "", winreg.REG_SZ, f'{exe_path} --send "%1"')
        winreg.CloseKey(key)


def _install_to_registry(root_key, exe_path: str):
    """Install context menu to specified registry root."""
    # Create main key
    key = winreg.CreateKey(root_key, CONTEXT_MENU_KEY)
    winreg.SetValue(key, "", winreg.REG_SZ, "Send with 2bshrd")
    winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, "")
    winreg.CloseKey(key)
    
    # Create command key
    key = winreg.CreateKey(root_key, CONTEXT_MENU_COMMAND_KEY)
    winreg.SetValue(key, "", winreg.REG_SZ, f'{exe_path} --send "%1"')
    winreg.CloseKey(key)


def uninstall_context_menu():
    """Remove the context menu from Windows Explorer."""
    # Try HKEY_CLASSES_ROOT
    try:
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, CONTEXT_MENU_COMMAND_KEY)
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, CONTEXT_MENU_KEY)
    except (FileNotFoundError, PermissionError):
        pass
    
    # Try HKEY_CURRENT_USER
    try:
        user_command_key = r"Software\Classes\*\shell\2bshrd\command"
        user_key = r"Software\Classes\*\shell\2bshrd"
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, user_command_key)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, user_key)
    except (FileNotFoundError, PermissionError):
        pass


def is_context_menu_installed() -> bool:
    """Check if context menu is installed."""
    try:
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, CONTEXT_MENU_KEY)
        return True
    except FileNotFoundError:
        pass
    
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\*\shell\2bshrd")
        return True
    except FileNotFoundError:
        pass
    
    return False
