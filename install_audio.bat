@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title EMERGENCE LAB - Optional audio support
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Run install.bat first.
    pause
    exit /b 1
)
set "VPY=.venv\Scripts\python.exe"
echo.
echo  Optional audio support for the Animated Companion mode - EXPERIMENTAL
echo  -------------------------------------------------------------------
echo  Packages: numpy, sounddevice with PortAudio, faster-whisper with CTranslate2.
echo  Download size of the packages: roughly 150-250 MB.
echo  Text mode keeps working without any of this.
echo.
echo  This script does NOT install virtual audio cable drivers. If you want isolated
echo  routing, install e.g. VB-CABLE yourself - see README, section "Audio setup".
echo.
choice /C YN /M "  Install the audio packages now"
if errorlevel 2 exit /b 0
"%VPY%" -m pip install --disable-pip-version-check -r requirements-audio.txt
if errorlevel 1 (
    echo [ERROR] Installing the audio packages failed.
    pause
    exit /b 1
)
echo.
echo  Speech recognition model for local transcription - downloaded from Hugging Face:
echo    1 = tiny    ~75 MB
echo    2 = base    ~145 MB   recommended to start
echo    3 = small   ~465 MB   better German / French accuracy
echo    4 = medium  ~1.5 GB
echo    5 = skip - you can download a model later in the audio setup wizard
choice /C 12345 /N /M "  Choose 1-5: "
set "CH=%ERRORLEVEL%"
set "M="
if "%CH%"=="1" set "M=tiny"
if "%CH%"=="2" set "M=base"
if "%CH%"=="3" set "M=small"
if "%CH%"=="4" set "M=medium"
if defined M "%VPY%" -m audio.stt_engine --download %M%
echo.
echo  Audio support installed. Configure it in the app: Guest = Animated Companion, then "Audio setup...".
pause
exit /b 0
