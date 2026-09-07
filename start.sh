#!/bin/bash
# Mbarara Auction System - Linux/macOS Startup Script
# Run this file to automatically setup and start the development server

echo ""
echo "============================================================"
echo "Mbarara Auction System - Auto Setup (Linux/macOS)"
echo "============================================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    echo "Please install Python 3.8+ first"
    echo "  macOS: brew install python@3.12"
    echo "  Linux: sudo apt install python3.12 python3.12-venv"
    exit 1
fi

# Run the Python startup script
python3 start.py "$@"
