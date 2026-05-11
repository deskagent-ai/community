@echo off
echo ========================================
echo   AI Assistant - Autostart entfernen
echo ========================================
echo.

set STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SHORTCUT_NAME=AI Assistant.lnk

if exist "%STARTUP_FOLDER%\%SHORTCUT_NAME%" (
    del "%STARTUP_FOLDER%\%SHORTCUT_NAME%"
    echo [OK] Autostart-Verknuepfung entfernt.
    echo.
    echo AI Assistant wird nicht mehr automatisch gestartet.
) else (
    echo [INFO] Keine Autostart-Verknuepfung gefunden.
)

echo.
pause
