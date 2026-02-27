@echo off
setlocal enabledelayedexpansion
title OpenSystemMonitor — Setup

:: ─────────────────────────────────────────────────────────────────────────────
::  Colour helpers (ANSI via PowerShell echo trick)
:: ─────────────────────────────────────────────────────────────────────────────
set "ESC="
for /f %%a in ('echo prompt $E ^| cmd /q') do set "ESC=%%a"
set "RESET=%ESC%[0m"
set "BOLD=%ESC%[1m"
set "GREEN=%ESC%[92m"
set "RED=%ESC%[91m"
set "CYAN=%ESC%[96m"
set "YELLOW=%ESC%[93m"

set "PASS=%GREEN%[PASS]%RESET%"
set "FAIL=%RED%[FAIL]%RESET%"
set "INFO=%CYAN%[INFO]%RESET%"
set "WARN=%YELLOW%[WARN]%RESET%"

set "ERRORS=0"

echo.
echo %BOLD%%CYAN%══════════════════════════════════════════════════════%RESET%
echo %BOLD%%CYAN%   OpenSystemMonitor — Setup ^& Verification%RESET%
echo %BOLD%%CYAN%   Modern Web Dashboard for ASUS Laptops%RESET%
echo %BOLD%%CYAN%══════════════════════════════════════════════════════%RESET%
echo.

:: ─────────────────────────────────────────────────────────────────────────────
::  STEP 1 — Admin check
:: ─────────────────────────────────────────────────────────────────────────────
echo %BOLD%[1/9] Checking Administrator privileges...%RESET%
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo   %FAIL% Not running as Administrator.
    echo.
    echo   %YELLOW%Please right-click setup.bat and choose%RESET%
    echo   %YELLOW%"Run as administrator", then try again.%RESET%
    echo.
    pause
    exit /b 1
)
echo   %PASS% Running as Administrator.
echo.

:: ─────────────────────────────────────────────────────────────────────────────
::  STEP 2 — Python version check (3.10+)
:: ─────────────────────────────────────────────────────────────────────────────
echo %BOLD%[2/9] Checking Python installation...%RESET%
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   %FAIL% Python not found in PATH.
    echo   %YELLOW%Install Python 3.10+ from https://python.org and ensure%RESET%
    echo   %YELLOW%"Add Python to PATH" is checked during install.%RESET%
    set /a ERRORS+=1
    goto :after_python
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)
echo   %INFO% Found Python !PYVER!

if !PY_MAJOR! LSS 3 (
    echo   %FAIL% Python 3.10 or higher required ^(found !PYVER!^).
    set /a ERRORS+=1
    goto :after_python
)
if !PY_MAJOR! EQU 3 if !PY_MINOR! LSS 10 (
    echo   %FAIL% Python 3.10 or higher required ^(found !PYVER!^).
    set /a ERRORS+=1
    goto :after_python
)
echo   %PASS% Python !PYVER! — OK.

:after_python
echo.

:: ─────────────────────────────────────────────────────────────────────────────
::  STEP 3 — Create virtual environment
:: ─────────────────────────────────────────────────────────────────────────────
echo %BOLD%[3/9] Setting up virtual environment...%RESET%
if exist ".venv\Scripts\python.exe" (
    echo   %INFO% .venv already exists — skipping creation.
) else (
    echo   %INFO% Creating .venv ...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo   %FAIL% Failed to create virtual environment.
        set /a ERRORS+=1
        goto :after_venv
    )
    echo   %PASS% Virtual environment created.
)

if not exist ".venv\Scripts\python.exe" (
    echo   %FAIL% .venv\Scripts\python.exe not found — venv may be corrupt.
    set /a ERRORS+=1
)

:after_venv
echo.

:: ─────────────────────────────────────────────────────────────────────────────
::  STEP 4 — Upgrade pip and install requirements
:: ─────────────────────────────────────────────────────────────────────────────
echo %BOLD%[4/9] Installing dependencies...%RESET%
echo   %INFO% Upgrading pip...
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
if %errorlevel% neq 0 (
    echo   %WARN% pip upgrade failed ^(non-critical, continuing^).
)

echo   %INFO% Installing from requirements.txt...
.venv\Scripts\pip.exe install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo   %FAIL% Dependency installation failed.
    echo   %YELLOW%Check your internet connection and try again.%RESET%
    set /a ERRORS+=1
) else (
    echo   %PASS% All packages installed successfully.
)
echo.

:: ─────────────────────────────────────────────────────────────────────────────
::  STEP 5 — Verify Python imports
:: ─────────────────────────────────────────────────────────────────────────────
echo %BOLD%[5/9] Verifying Python package imports...%RESET%

set "PKGS=fastapi uvicorn psutil pydantic requests pynvml clr wmi"
for %%p in (%PKGS%) do (
    .venv\Scripts\python.exe -c "import %%p" >nul 2>&1
    if !errorlevel! equ 0 (
        echo   %PASS% %%p
    ) else (
        echo   %FAIL% %%p  ^(import failed^)
        set /a ERRORS+=1
    )
)
echo.

:: ─────────────────────────────────────────────────────────────────────────────
::  STEP 6 — Check required DLLs in server/libs/
:: ─────────────────────────────────────────────────────────────────────────────
echo %BOLD%[6/9] Checking DLL files...%RESET%
set "DLLS=server\libs\LibreHardwareMonitorLib.dll server\libs\System.Management.dll"
for %%d in (%DLLS%) do (
    if exist "%%d" (
        echo   %PASS% %%d
    ) else (
        echo   %FAIL% %%d  ^(file missing!^)
        set /a ERRORS+=1
    )
)
echo.

:: ─────────────────────────────────────────────────────────────────────────────
::  STEP 7 — Check dashboard and utility files
:: ─────────────────────────────────────────────────────────────────────────────
echo %BOLD%[7/9] Checking project files...%RESET%
set "FILES=server\main.py webDashboard\dashboard.html monitor.bat server\show_mobile_access.py server\verify_server.py"
for %%f in (%FILES%) do (
    if exist "%%f" (
        echo   %PASS% %%f
    ) else (
        echo   %FAIL% %%f  ^(file missing!^)
        set /a ERRORS+=1
    )
)
echo.

:: ─────────────────────────────────────────────────────────────────────────────
::  STEP 8 — ATK ACPI driver check
:: ─────────────────────────────────────────────────────────────────────────────
echo %BOLD%[8/9] Checking ATK ACPI driver...%RESET%
.venv\Scripts\python.exe -c ^
"import ctypes, ctypes.wintypes as wt; k=ctypes.windll.kernel32; h=k.CreateFileW('\\\\.\\ATKACPI',0xC0000000,3,None,3,0x80,None); ok=h!=-1; k.CloseHandle(h) if ok else None; exit(0 if ok else 1)" >nul 2>&1
if %errorlevel% equ 0 (
    echo   %PASS% ATKACPI device accessible — fan speed ^& mode control ready.
) else (
    echo   %WARN% ATKACPI device not accessible.
    echo   %YELLOW%        This is normal on non-ASUS hardware.%RESET%
    echo   %YELLOW%        Fan speeds and performance modes will show N/A.%RESET%
)
echo.

:: ─────────────────────────────────────────────────────────────────────────────
::  STEP 9 — Check network connectivity for mobile access
:: ─────────────────────────────────────────────────────────────────────────────
echo %BOLD%[9/9] Checking network connectivity...%RESET%
powershell -NoProfile -Command "$wifi = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' }; if ($wifi) { Write-Host '  [PASS] WiFi connected - mobile access available' -ForegroundColor Green; $wifi | ForEach-Object { Write-Host ('         Mobile URL: http://' + $_.IPAddress + ':8080') -ForegroundColor Cyan } } else { Write-Host '  [WARN] No WiFi connection detected' -ForegroundColor Yellow; Write-Host '         Mobile access will not work until connected to WiFi' -ForegroundColor Yellow }"
echo.

:: ─────────────────────────────────────────────────────────────────────────────
::  Summary
:: ─────────────────────────────────────────────────────────────────────────────
echo %BOLD%%CYAN%══════════════════════════════════════════════════════%RESET%
if !ERRORS! equ 0 (
    echo %BOLD%%GREEN%  ✓ Setup complete — no errors found!%RESET%
    echo.
    echo   %BOLD%Next Steps:%RESET%
    echo   1. Run %BOLD%monitor.bat%RESET% as Administrator to start the server
    echo   2. Open http://localhost:8080 in your browser
    echo   3. For mobile access, run %BOLD%mobile_info.bat%RESET% to get WiFi URL
    echo   4. Optional: Run %BOLD%setup_firewall.bat%RESET% as Admin for mobile access
    echo.
    echo   %BOLD%Features:%RESET%
    echo   • Real-time dashboard with auto-refresh
    echo   • CPU, GPU, memory, disk, network monitoring
    echo   • Temperature sensors and fan speeds
    echo   • Performance mode controls (CPU/GPU)
    echo   • Mobile-responsive design
    echo   • WiFi access from any device on same network
) else (
    echo %BOLD%%RED%  ✗ Setup finished with !ERRORS! error(s).%RESET%
    echo.
    echo   Fix the issues above and re-run setup.bat.
)
echo %BOLD%%CYAN%══════════════════════════════════════════════════════%RESET%
echo.
pause
endlocal
