@echo off
echo ========================================
echo   AI Assistant - Autostart einrichten
echo ========================================
echo.

set STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SHORTCUT_NAME=AI Assistant.lnk
set TARGET_BAT=%~dp0start.bat

:: Create shortcut using PowerShell
echo Erstelle Autostart-Verknuepfung...
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%STARTUP_FOLDER%\%SHORTCUT_NAME%'); $s.TargetPath = '%TARGET_BAT%'; $s.WorkingDirectory = '%~dp0'; $s.WindowStyle = 7; $s.Save()"

if exist "%STARTUP_FOLDER%\%SHORTCUT_NAME%" (
    echo.
    echo [OK] Autostart eingerichtet!
    echo.
    echo     Verknuepfung: %STARTUP_FOLDER%\%SHORTCUT_NAME%
    echo     Ziel: %TARGET_BAT%
    echo.
    echo AI Assistant wird jetzt bei jedem Windows-Start automatisch gestartet.
    echo.
    echo Zum Entfernen: autostart-remove.bat ausfuehren
) else (
    echo.
    echo [ERROR] Verknuepfung konnte nicht erstellt werden!
)

echo.
pause
