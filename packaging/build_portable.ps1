<#
.SYNOPSIS
    Builds the EMERGENCE LAB portable Windows x64 distribution (PyInstaller one-folder).

.DESCRIPTION
    Creates an isolated build virtual environment, installs the build and runtime dependencies,
    runs PyInstaller with packaging/EmergenceLab.spec, adds the top-level documents, verifies the
    layout and (unless -SkipZip) writes dist\EmergenceLab-<version>-win-x64[-audio].zip.

    Only the BUILD machine needs Python. The resulting folder runs without Python, Node.js or
    administrator rights.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build_portable.ps1
    powershell -ExecutionPolicy Bypass -File packaging\build_portable.ps1 -Variant audio
#>
[CmdletBinding()]
param(
    [ValidateSet('core', 'audio')]
    [string]$Variant = 'core',
    [string]$Python = '',
    [switch]$SkipZip,
    [switch]$ZipOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VersionMatch = Select-String -Path (Join-Path $Root 'app\__init__.py') -Pattern '__version__ = "([^"]+)"'
if (-not $VersionMatch) { throw 'Could not read __version__ from app\__init__.py' }
$Version = $VersionMatch.Matches[0].Groups[1].Value
$DistName = "EmergenceLab-$Version-win-x64" + $(if ($Variant -eq 'audio') { '-audio' } else { '' })
$DistRoot = Join-Path $Root "dist\$Variant"
$AppDir = Join-Path $DistRoot $DistName
$ZipPath = Join-Path $Root "dist\$DistName.zip"

function Invoke-Native {
    # Native tools (pip, PyInstaller) log to stderr. Judge them by exit code only, so Windows PowerShell 5.1
    # does not turn stderr lines into terminating errors.
    param([string]$Exe, [string[]]$Arguments)
    Write-Host "> $Exe $($Arguments -join ' ')" -ForegroundColor DarkGray
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Exe @Arguments; $code = $LASTEXITCODE } finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw "Command failed with exit code ${code}: $Exe $($Arguments -join ' ')" }
}

function New-PortableZip {
    if (-not (Test-Path (Join-Path $AppDir 'EmergenceLab.exe'))) { throw "No build found at $AppDir" }
    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
    Write-Host "Creating $ZipPath ..."
    Compress-Archive -Path $AppDir -DestinationPath $ZipPath -CompressionLevel Optimal
    $size = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
    Write-Host "Portable ZIP ready: $ZipPath ($size MB)" -ForegroundColor Green
}

if ($ZipOnly) { New-PortableZip; return }

Write-Host "EMERGENCE LAB $Version - portable build ($Variant)" -ForegroundColor Cyan

# ---------------------------------------------------------------- build interpreter
if ($Python) {
    $PyExe = $Python; $PyArgs = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PyExe = 'py'; $PyArgs = @('-3')
    foreach ($candidate in @('-3.12', '-3.13', '-3.11')) {     # versions with PySide6 wheels, preferred order
        $previous = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        & py $candidate -c 'import sys' 2>$null | Out-Null
        $found = ($LASTEXITCODE -eq 0); $ErrorActionPreference = $previous
        if ($found) { $PyArgs = @($candidate); break }
    }
} else {
    $PyExe = 'python'; $PyArgs = @()
}
# (no double quotes inside native arguments: Windows PowerShell 5.1 would strip them)
try {
    Invoke-Native $PyExe ($PyArgs + @('-c', 'import struct, sys; print(sys.version); sys.exit(0 if sys.version_info >= (3, 11) and struct.calcsize(''P'') == 8 else 1)'))
} catch {
    throw "A 64-bit Python 3.11 or newer is required on the build computer ($PyExe $PyArgs)."
}

$Venv = Join-Path $Root "build\venv-$Variant"
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $VenvPy)) { Invoke-Native $PyExe ($PyArgs + @('-m', 'venv', $Venv)) }

$Reqs = @('-r', 'packaging\requirements-build.txt', '-r', 'requirements.txt')
if ($Variant -eq 'audio') { $Reqs += @('-r', 'requirements-audio.txt') }
Invoke-Native $VenvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', 'pip')
Invoke-Native $VenvPy (@('-m', 'pip', 'install', '--disable-pip-version-check') + $Reqs)

# ---------------------------------------------------------------- PyInstaller
if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
$env:EL_VARIANT = $Variant
Invoke-Native $VenvPy @('-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', $DistRoot,
                        '--workpath', (Join-Path $Root "build\pyinstaller-$Variant"), 'packaging\EmergenceLab.spec')

# ---------------------------------------------------------------- top-level documents
Copy-Item (Join-Path $Root 'README.md') $AppDir
Copy-Item (Join-Path $Root 'CHANGELOG.md') $AppDir
Copy-Item (Join-Path $Root 'packaging\READ-ME-FIRST.txt') $AppDir
$PyVersion = & $VenvPy -c "import sys; print(sys.version.split()[0])"
$PyiVersion = & $VenvPy -c "import PyInstaller; print(PyInstaller.__version__)"
$QtVersion = & $VenvPy -c "import PySide6; print(PySide6.__version__)"
$PwVersion = & $VenvPy -c "from importlib.metadata import version; print(version('playwright'))"
$Commit = if ($env:GITHUB_SHA) { $env:GITHUB_SHA } else { 'local build' }
@(
    "EMERGENCE LAB - AI Conversation Bridge $Version"
    "Variant:      $Variant"
    "Built:        $((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm')) UTC"
    "Commit:       $Commit"
    "Python:       $PyVersion (bundled)"
    "PyInstaller:  $PyiVersion"
    "PySide6:      $QtVersion"
    "Playwright:   $PwVersion (driver bundled; Firefox browser runtime NOT bundled - optional download)"
    "Audio:        $(if ($Variant -eq 'audio') { 'numpy, sounddevice, faster-whisper bundled (models downloaded on request)' } else { 'not included' })"
) | Set-Content -Path (Join-Path $AppDir 'BUILD-INFO.txt') -Encoding UTF8

# ---------------------------------------------------------------- verify layout
$required = @('EmergenceLab.exe', 'EmergenceLab-console.exe', 'READ-ME-FIRST.txt', 'README.md',
              '_internal\config\providers.json', '_internal\config\defaults.json',
              '_internal\assets\mock_chat.html', '_internal\playwright\driver\node.exe',
              '_internal\playwright\driver\package\cli.js')
foreach ($f in $required) {
    if (-not (Test-Path (Join-Path $AppDir $f))) { throw "Build verification failed: missing $f" }
}
$forbidden = Get-ChildItem $AppDir -Recurse -File -Include 'settings.json', 'sessions.sqlite3', '*.log', 'providers.user.json' -ErrorAction SilentlyContinue
if ($forbidden) { throw "Build verification failed: user data inside the application folder: $($forbidden.FullName -join ', ')" }
$sizeMB = [math]::Round(((Get-ChildItem $AppDir -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
Write-Host "Portable folder ready: $AppDir ($sizeMB MB)" -ForegroundColor Green

if (-not $SkipZip) { New-PortableZip }
