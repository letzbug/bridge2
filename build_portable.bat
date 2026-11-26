@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title EMERGENCE LAB - portable build
echo  Builds the portable Windows distribution into the dist folder.
echo  This needs Python 3.11+ on THIS build computer only. Usage: build_portable.bat [core^|audio]
set "VARIANT=%~1"
if "%VARIANT%"=="" set "VARIANT=core"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\build_portable.ps1" -Variant %VARIANT%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo [ERROR] Build failed with exit code %RC%.
pause
exit /b %RC%
