@echo off
:: Check Python Environment for DeskAgent Development
:: Ensures embedded Python is correctly set up for consistent Dev/Prod behavior

cd /d "%~dp0"

echo.
echo === DeskAgent Python Environment Check ===
echo.

:: Check if embedded Python exists
if exist "python\python.exe" (
    echo [OK] Embedded Python gefunden
    echo     Pfad: %~dp0python\python.exe
    echo.

    :: Show version
    echo Python Version:
    python\python.exe --version
    echo.

    :: Check critical packages
    echo Kritische Packages:
    echo -------------------
    python\python.exe -m pip list 2>nul | findstr /i "mcp anthropic google-genai spacy presidio"
    echo.

    :: Check if requirements are up to date
    echo Requirements Check:
    echo -------------------
    python\python.exe -m pip check 2>nul
    if %ERRORLEVEL% neq 0 (
        echo [WARNING] Einige Package-Dependencies fehlen
        echo           Fuehre aus: python\python.exe -m pip install -r requirements.txt
    ) else (
        echo [OK] Alle Dependencies installiert
    )
    echo.

    :: Show python312._pth config
    if exist "python\python312._pth" (
        echo python312._pth Konfiguration:
        echo ------------------------------
        type "python\python312._pth"
        echo.
    )

    echo.
    echo === Check abgeschlossen ===
    echo Embedded Python ist korrekt eingerichtet.
    echo.

) else (
    echo [FEHLER] Embedded Python NICHT installiert!
    echo.
    echo         Pfad nicht gefunden: %~dp0python\python.exe
    echo.
    echo         Fuehre aus: setup-python.bat
    echo.
    echo         Dies stellt sicher, dass Development und Production
    echo         dieselbe Python-Umgebung nutzen.
    echo.
    exit /b 1
)

pause
