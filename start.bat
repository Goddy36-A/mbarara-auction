@echo off
title Mbarara Auction — Local Server
python start.py
if errorlevel 1 (
    echo.
    echo Something went wrong. Read the errors above.
    pause
)
