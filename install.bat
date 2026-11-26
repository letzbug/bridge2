@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title EMERGENCE LAB - Installer
echo.
echo  ==============================================================
echo   EMERGENCE LAB - AI Conversation Bridge v0.1.1 - Installer
echo   Built by Frank G - IBM Certified AI Developer
echo  ==============================================================
echo.
echo  This installer does NOT need administrator rights. It creates a local
echo  virtual environment in this folder and data folders in your user profile.
echo.

set "BROWSER_CHOICE="
if /I "%~1"=="/browser" set "BROWSER_CHOICE=Y"
if /I "%~1"=="/nobrowser" set "BROWSER_CHOICE=N"

rem ---------------------------------------------------------------- 1. Python 3.11+
set "PY="
for %%V in (3.12 3.13 3.11 3.14) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python 3.11 or newer was not found.
    echo         Install it from https://www.python.org/downloads/windows/
    echo         and tick "Add python.exe to PATH" during setup. Then run install.bat again.
    goto :fail
)
for /f "delims=" %%I in ('%PY% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%I"
echo [1/5] Python %PYVER% found  [%PY%]

rem ---------------------------------------------------------------- 2. virtual environment
if exist ".venv\Scripts\python.exe" (
    echo [2/5] Using the existing virtual environment .venv
) else (
    echo [2/5] Creating the virtual environment .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] The virtual environment could not be created.
        goto :fail
    )
)
set "VPY=.venv\Scripts\python.exe"

rem ---------------------------------------------------------------- 3. core dependencies
echo [3/5] Installing core dependencies: PySide6, Playwright ...
"%VPY%" -m pip install --upgrade pip --disable-pip-version-check >nul
"%VPY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Installing the dependencies failed. Check the internet connection and run install.bat again.
    goto :fail
)

rem ---------------------------------------------------------------- 4. browser runtime
if not defined BROWSER_CHOICE (
    echo.
    echo [4/5] Automated browser adapters need Playwright's MANAGED FIREFOX BUILD.
    echo       This is a separate Firefox build, about 80-100 MB, stored in your user profile.
    echo       It does not touch your installed Firefox or your Firefox profile.
    echo       Not needed for demo mode, clipboard mode or the installed-Firefox backend.
    choice /C YN /M "      Install the Playwright-managed Firefox now"
    if errorlevel 2 (set "BROWSER_CHOICE=N") else (set "BROWSER_CHOICE=Y")
)
if /I "%BROWSER_CHOICE%"=="Y" (
    echo [4/5] Installing the Playwright-managed Firefox ...
    "%VPY%" -m playwright install firefox
    if errorlevel 1 (
        echo [WARN] The browser runtime could not be installed. Demo and clipboard mode still work.
        echo        Retry later with:  .venv\Scripts\python -m playwright install firefox
    )
) else (
    echo [4/5] Browser runtime skipped. Install it later with:
    echo        .venv\Scripts\python -m playwright install firefox
)

rem ---------------------------------------------------------------- 5. directories + self-check
echo [5/5] Creating local application directories ...
"%VPY%" -m app.paths --init
if errorlevel 1 goto :fail
echo.
"%VPY%" main.py --self-check
if errorlevel 1 echo [WARN] The self-check reported a problem - see above.

echo.
echo  Installation complete.
echo    Start:           start.bat
echo    Demo mode:       start.bat --demo
echo    Optional audio:  install_audio.bat
echo.
pause
exit /b 0

:fail
echo.
echo  Installation did not complete.
pause
exit /b 1
