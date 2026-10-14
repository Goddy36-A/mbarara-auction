@echo off
REM Mbarara Auction System - Windows Startup Script
REM Run this file to automatically setup and start the development server

setlocal enabledelayedexpansion

title Mbarara Auction System

echo.
echo ============================================================
echo Mbarara Auction System - Auto Setup (Windows)
echo ============================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://www.python.org
    echo Make sure to check "Add Python to PATH" during installation
    pause
    exit /b 1
)

REM Run the Python startup script
python start.py %*
set EXITCODE=%errorlevel%

echo.
if %EXITCODE% neq 0 (
    echo ============================================================
    echo Setup stopped with an error, code %EXITCODE%.
    echo Read the messages above to see what went wrong.
    echo ============================================================
) else (
    echo Server stopped.
)

REM Keep the window open so the messages can be read
pause
exit /b %EXITCODE%
