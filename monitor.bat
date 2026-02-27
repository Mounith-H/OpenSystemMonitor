@echo off
setlocal EnableDelayedExpansion
title Remote System Monitor

set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"
set "UVICORN=%ROOT%.venv\Scripts\uvicorn.exe"
set "SERVER_DIR=%ROOT%server"
set "LOG_DIR=%ROOT%logs"
set "SERVER_LOG=%LOG_DIR%\server.log"
set "PORT=8080"
set "RSM_DISABLE_LHM=0"
set "RSM_LHM_MODE=subprocess"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo.
echo  ============================================================
echo   Remote System Monitor
echo  ============================================================

net session >nul 2>&1
if %errorlevel%==0 (
    echo   [OK] Running as Administrator - CPU temps available
) else (
    echo   [!] Not Administrator - CPU temps will be N/A
    echo   Right-click this bat file and "Run as administrator" for full data
)
echo.

echo  Stopping any existing server on port %PORT%...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %PORT% -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
timeout /t 1 /nobreak >nul

echo  Starting server (http://0.0.0.0:%PORT%)...
echo  Server log: %SERVER_LOG%
start "RSM Server" /D "%SERVER_DIR%" /min cmd /c ""%UVICORN%" main:app --host 0.0.0.0 --port %PORT% > "%SERVER_LOG%" 2>&1"

echo  Waiting for server to be ready...
set READY=0
for /l %%i in (1,1,15) do (
    if !READY!==0 (
        "%PYTHON%" "%SERVER_DIR%\_check_health.py" >nul 2>&1
        if !errorlevel!==0 (
            set READY=1
            echo  Server is ready!
        ) else (
            timeout /t 1 /nobreak >nul
        )
    )
)
if !READY!==0 (
    echo  ERROR: Server did not start within 15 seconds.
    pause
    goto :EOF
)

echo.
echo  ============================================================
echo   Server is running! Access URLs:
echo  ============================================================
echo   Local:  http://localhost:%PORT%
echo.

REM Show WiFi IP addresses for mobile access (exclude link-local 169.254.x.x)
powershell -NoProfile -Command "$interfaces = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' }; if ($interfaces) { Write-Host '  Mobile/WiFi URLs:' -ForegroundColor Cyan; $interfaces | ForEach-Object { Write-Host ('  http://' + $_.IPAddress + ':%PORT%') -ForegroundColor Green }; Write-Host '' } else { Write-Host '  No WiFi connection for mobile access' -ForegroundColor Yellow; Write-Host '' }"

echo  TIP: Open any URL above in your browser to access the dashboard
echo  ============================================================

:MENU
echo.
echo  ============================================================
echo   What do you want to do?
echo  ============================================================
echo    [1]  Run verify_server.py
echo    [2]  Show mobile access URLs
echo    [3]  Quit  ^(stop server^)
echo    [4]  Quit  ^(leave server running^)
echo    [5]  Restart server
echo.
set /p CHOICE=  Enter choice: 

if "!CHOICE!"=="1" (
    echo.
    echo  ------------------------------------------------------------
    "%PYTHON%" "%SERVER_DIR%\verify_server.py" --host localhost --port %PORT%
    echo  ------------------------------------------------------------
    goto MENU
)
if "!CHOICE!"=="2" (
    echo.
    "%PYTHON%" "%SERVER_DIR%\show_mobile_access.py"
    goto MENU
)
if "!CHOICE!"=="3" (
    echo.
    powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %PORT% -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
    echo  Server stopped. Goodbye.
    timeout /t 1 /nobreak >nul
    goto :EOF
)
if "!CHOICE!"=="4" (
    echo.
    echo  Server still running on http://localhost:%PORT%
    echo  Goodbye.
    goto :EOF
)
if "!CHOICE!"=="5" (
    echo.
    echo  Restarting server on port %PORT%...
    powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %PORT% -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
    timeout /t 1 /nobreak >nul

    echo  Server log: %SERVER_LOG%
    start "RSM Server" /D "%SERVER_DIR%" /min cmd /c ""%UVICORN%" main:app --host 0.0.0.0 --port %PORT% > "%SERVER_LOG%" 2>&1"

    echo  Waiting for server to be ready...
    set READY=0
    for /l %%i in (1,1,15) do (
        if !READY!==0 (
            "%PYTHON%" "%SERVER_DIR%\_check_health.py" >nul 2>&1
            if !errorlevel!==0 (
                set READY=1
                echo  Server restarted successfully!
            ) else (
                timeout /t 1 /nobreak >nul
            )
        )
    )
    if !READY!==0 (
        echo  ERROR: Server did not restart within 15 seconds.
    )
    goto MENU
)
echo  Invalid choice. Enter 1, 2, 3, 4 or 5.
goto MENU