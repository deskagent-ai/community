@echo off
:: DeskAgent Stop Script - Uses PID file as primary method

set "PID_FILE=%~dp0deskagent.pid"

:: Method 1: PID file (primary, most reliable)
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    if defined PID (
        echo [INFO] Stopping DeskAgent...
        taskkill /PID %PID% /T /F >nul 2>&1
        del "%PID_FILE%" 2>nul
        ping -n 2 127.0.0.1 >nul
        echo [INFO] DeskAgent stopped.
        goto :eof
    )
)

:: Method 2: HTTP shutdown (if PID file missing)
curl -X POST http://localhost:8765/shutdown -s -o nul 2>nul
if %errorlevel% equ 0 (
    echo [INFO] HTTP shutdown sent.
    ping -n 3 127.0.0.1 >nul
    goto :eof
)

echo [INFO] No running DeskAgent found.
