#!/bin/bash
# Quick install script for Linux/macOS

set -e

echo "Installing 2bshrd..."

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is required. Install it first."
    exit 1
fi

# Use uv if available, otherwise pip
if command -v uv &> /dev/null; then
    echo "Using uv..."
    uv pip install -r requirements.txt
    echo ""
    echo "✓ Installed! Run with: uv run python -m shrd"
else
    echo "Using pip..."
    pip3 install -r requirements.txt
    echo ""
    echo "✓ Installed! Run with: python3 -m shrd"
fi

echo ""
echo "To run on startup, add to your startup applications:"
echo "  python3 -m shrd"
