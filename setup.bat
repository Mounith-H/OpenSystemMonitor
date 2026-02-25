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
echo %BOLD%%CYAN%══════════════════════════════════════════════════════%RESET%
echo.

:: ─────────────────────────────────────────────────────────────────────────────
::  STEP 1 — Admin check
:: ─────────────────────────────────────────────────────────────────────────────
echo %BOLD%[1/7] Checking Administrator privileges...%RESET%
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
echo %BOLD%[2/7] Checking Python installation...%RESET%
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
echo %BOLD%[3/7] Setting up virtual environment...%RESET%
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
echo %BOLD%[4/7] Installing dependencies...%RESET%
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
echo %BOLD%[5/7] Verifying Python package imports...%RESET%

set "PKGS=fastapi uvicorn psutil pydantic pynvml clr wmi"
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
::  STEP 6 — Check required DLLs in libs/
:: ─────────────────────────────────────────────────────────────────────────────
echo %BOLD%[6/7] Checking DLL files...%RESET%
set "DLLS=libs\LibreHardwareMonitorLib.dll libs\System.Management.dll"
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
::  STEP 7 — ATK ACPI driver check
:: ─────────────────────────────────────────────────────────────────────────────
echo %BOLD%[7/7] Checking ATK ACPI driver...%RESET%
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
::  Summary
:: ─────────────────────────────────────────────────────────────────────────────
echo %BOLD%%CYAN%══════════════════════════════════════════════════════%RESET%
if !ERRORS! equ 0 (
    echo %BOLD%%GREEN%  Setup complete — no errors found!%RESET%
    echo.
    echo   Run %BOLD%monitor.bat%RESET% as Administrator to start the server.
) else (
    echo %BOLD%%RED%  Setup finished with !ERRORS! error(s).%RESET%
    echo.
    echo   Fix the issues above and re-run setup.bat.
)
echo %BOLD%%CYAN%══════════════════════════════════════════════════════%RESET%
echo.
pause
endlocal
