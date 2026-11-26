@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title EMERGENCE LAB - AI Conversation Bridge
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] EMERGENCE LAB is not installed yet. Run install.bat first.
    pause
    exit /b 1
)
echo  EMERGENCE LAB - AI Conversation Bridge v0.1.1
echo  Keep this window open while the application runs. No conversation starts automatically.
".venv\Scripts\python.exe" main.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [ERROR] EMERGENCE LAB exited with code %RC%.
    echo         Log file:   %LOCALAPPDATA%\EmergenceLab\logs\emergence-lab.log
    echo         Self-check: start.bat --self-check
    pause
)
exit /b %RC%
