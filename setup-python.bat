@echo off
echo ========================================
echo DeskAgent - Python Setup
echo ========================================

:: Python-Version aus zentraler Datei lesen (python-version.txt)
:: WICHTIG: Python 3.12 verwenden - spacy/thinc ist noch nicht mit 3.13 kompatibel!
set /p PYTHON_VERSION=<"%~dp0python-version.txt"
set PYTHON_DIR=%~dp0python
echo Using Python %PYTHON_VERSION%

if exist "%PYTHON_DIR%\python.exe" (
    echo Python bereits vorhanden: %PYTHON_DIR%
    echo Zum Neuinstallieren erst deskagent\python\ loeschen.
    pause
    exit /b 0
)

echo.
echo [1/5] Downloading Python %PYTHON_VERSION% embeddable...
mkdir "%PYTHON_DIR%" 2>nul
powershell -Command "& {$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-embed-amd64.zip' -OutFile '%PYTHON_DIR%\python-embed.zip'}"

if not exist "%PYTHON_DIR%\python-embed.zip" (
    echo [ERROR] Download failed!
    pause
    exit /b 1
)

echo [2/5] Extracting...
powershell -Command "Expand-Archive -Path '%PYTHON_DIR%\python-embed.zip' -DestinationPath '%PYTHON_DIR%' -Force"
del "%PYTHON_DIR%\python-embed.zip"

echo [3/5] Configuring Python path...
(
echo python312.zip
echo .
echo Lib
echo Lib\site-packages
echo import site
) > "%PYTHON_DIR%\python312._pth"

echo [4/5] Installing pip and dependencies...
powershell -Command "& {$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%PYTHON_DIR%\get-pip.py'}"
"%PYTHON_DIR%\python.exe" "%PYTHON_DIR%\get-pip.py" --no-warn-script-location

echo.
echo Installing dependencies from requirements.txt...
"%PYTHON_DIR%\python.exe" -m pip install -r "%~dp0requirements.txt" --no-warn-script-location

echo.
echo [5/5] Copying stdlib modules (email, etc.)...
:: Embedded Python fehlt manchmal stdlib-Submodule wie email.mime
:: Kopiere vom System-Python falls vorhanden

mkdir "%PYTHON_DIR%\Lib" 2>nul

:: Method 1: Use py launcher
for /f "delims=" %%p in ('py -3 -c "import email; import os; print(os.path.dirname(email.__file__))" 2^>nul') do (
    if exist "%%p\mime" (
        xcopy /E /I /Y /Q "%%p" "%PYTHON_DIR%\Lib\email" >nul 2>&1
        echo       email module copied from: %%p
    )
)

:: Method 2: Use python directly if py failed
if not exist "%PYTHON_DIR%\Lib\email\mime" (
    for /f "delims=" %%p in ('python -c "import email; import os; print(os.path.dirname(email.__file__))" 2^>nul') do (
        if exist "%%p\mime" (
            xcopy /E /I /Y /Q "%%p" "%PYTHON_DIR%\Lib\email" >nul 2>&1
            echo       email module copied from: %%p
        )
    )
)

:: Method 3: Common Python locations
if not exist "%PYTHON_DIR%\Lib\email\mime" (
    for %%v in (312 311 310) do (
        if not exist "%PYTHON_DIR%\Lib\email\mime" (
            if exist "C:\Python%%v\Lib\email\mime" (
                xcopy /E /I /Y /Q "C:\Python%%v\Lib\email" "%PYTHON_DIR%\Lib\email" >nul 2>&1
                echo       email module copied from: C:\Python%%v\Lib\email
            )
        )
        if not exist "%PYTHON_DIR%\Lib\email\mime" (
            if exist "%LOCALAPPDATA%\Programs\Python\Python%%v\Lib\email\mime" (
                xcopy /E /I /Y /Q "%LOCALAPPDATA%\Programs\Python\Python%%v\Lib\email" "%PYTHON_DIR%\Lib\email" >nul 2>&1
                echo       email module copied from: %LOCALAPPDATA%\Programs\Python\Python%%v\Lib\email
            )
        )
    )
)

:: Verify email
if exist "%PYTHON_DIR%\Lib\email\mime" (
    echo       email.mime: OK
) else (
    echo       [WARNING] email module not found - gmail/imap MCP may not work
)

:: Copy sqlite3 module (needed for datastore MCP)
:: sqlite3 consists of: Lib/sqlite3/ folder + _sqlite3.pyd + sqlite3.dll

:: Method 1: Use py launcher to find sqlite3 folder
for /f "delims=" %%p in ('py -3 -c "import sqlite3; import os; print(os.path.dirname(sqlite3.__file__))" 2^>nul') do (
    if exist "%%p\__init__.py" (
        xcopy /E /I /Y /Q "%%p" "%PYTHON_DIR%\Lib\sqlite3" >nul 2>&1
        echo       sqlite3 module copied from: %%p
    )
)

:: Method 2: Use python directly if py failed
if not exist "%PYTHON_DIR%\Lib\sqlite3\__init__.py" (
    for /f "delims=" %%p in ('python -c "import sqlite3; import os; print(os.path.dirname(sqlite3.__file__))" 2^>nul') do (
        if exist "%%p\__init__.py" (
            xcopy /E /I /Y /Q "%%p" "%PYTHON_DIR%\Lib\sqlite3" >nul 2>&1
            echo       sqlite3 module copied from: %%p
        )
    )
)

:: Method 3: Common Python locations
if not exist "%PYTHON_DIR%\Lib\sqlite3\__init__.py" (
    for %%v in (312 311 310) do (
        if not exist "%PYTHON_DIR%\Lib\sqlite3\__init__.py" (
            if exist "C:\Python%%v\Lib\sqlite3\__init__.py" (
                xcopy /E /I /Y /Q "C:\Python%%v\Lib\sqlite3" "%PYTHON_DIR%\Lib\sqlite3" >nul 2>&1
                echo       sqlite3 module copied from: C:\Python%%v\Lib\sqlite3
            )
        )
        if not exist "%PYTHON_DIR%\Lib\sqlite3\__init__.py" (
            if exist "%LOCALAPPDATA%\Programs\Python\Python%%v\Lib\sqlite3\__init__.py" (
                xcopy /E /I /Y /Q "%LOCALAPPDATA%\Programs\Python\Python%%v\Lib\sqlite3" "%PYTHON_DIR%\Lib\sqlite3" >nul 2>&1
                echo       sqlite3 module copied from: %LOCALAPPDATA%\Programs\Python\Python%%v\Lib\sqlite3
            )
        )
    )
)

:: Copy _sqlite3.pyd (C extension) - needed for sqlite3 to work
:: Try to find it next to the python.exe of system Python
for /f "delims=" %%p in ('py -3 -c "import sys; print(sys.prefix)" 2^>nul') do (
    if exist "%%p\DLLs\_sqlite3.pyd" (
        copy /Y "%%p\DLLs\_sqlite3.pyd" "%PYTHON_DIR%\" >nul 2>&1
        echo       _sqlite3.pyd copied from: %%p\DLLs
    )
    if exist "%%p\DLLs\sqlite3.dll" (
        copy /Y "%%p\DLLs\sqlite3.dll" "%PYTHON_DIR%\" >nul 2>&1
    )
)

:: Fallback: Common locations for DLLs
if not exist "%PYTHON_DIR%\_sqlite3.pyd" (
    for %%v in (312 311 310) do (
        if not exist "%PYTHON_DIR%\_sqlite3.pyd" (
            if exist "C:\Python%%v\DLLs\_sqlite3.pyd" (
                copy /Y "C:\Python%%v\DLLs\_sqlite3.pyd" "%PYTHON_DIR%\" >nul 2>&1
                copy /Y "C:\Python%%v\DLLs\sqlite3.dll" "%PYTHON_DIR%\" >nul 2>&1
                echo       sqlite3 DLLs copied from: C:\Python%%v\DLLs
            )
        )
        if not exist "%PYTHON_DIR%\_sqlite3.pyd" (
            if exist "%LOCALAPPDATA%\Programs\Python\Python%%v\DLLs\_sqlite3.pyd" (
                copy /Y "%LOCALAPPDATA%\Programs\Python\Python%%v\DLLs\_sqlite3.pyd" "%PYTHON_DIR%\" >nul 2>&1
                copy /Y "%LOCALAPPDATA%\Programs\Python\Python%%v\DLLs\sqlite3.dll" "%PYTHON_DIR%\" >nul 2>&1
                echo       sqlite3 DLLs copied from: %LOCALAPPDATA%\Programs\Python\Python%%v\DLLs
            )
        )
    )
)

:: Verify sqlite3
if exist "%PYTHON_DIR%\Lib\sqlite3\__init__.py" (
    if exist "%PYTHON_DIR%\_sqlite3.pyd" (
        echo       sqlite3: OK
    ) else (
        echo       [WARNING] sqlite3 module found but _sqlite3.pyd missing - datastore MCP may not work
    )
) else (
    echo       [WARNING] sqlite3 module not found - datastore MCP may not work
)

echo.
echo [6/6] Installing spaCy models (optional, ~600 MB)...
echo       This enables PII anonymization.
echo       Press Ctrl+C to skip if not needed.
echo.
"%PYTHON_DIR%\python.exe" -m spacy download de_core_news_lg
if %ERRORLEVEL% equ 0 (
    echo       de_core_news_lg: OK
) else (
    echo       [WARNING] de_core_news_lg failed - anonymization may not work for German
)
"%PYTHON_DIR%\python.exe" -m spacy download en_core_web_lg
if %ERRORLEVEL% equ 0 (
    echo       en_core_web_lg: OK
) else (
    echo       [WARNING] en_core_web_lg failed - anonymization may not work for English
)

echo.
echo ========================================
echo Python Setup Complete!
echo ========================================
echo Location: %PYTHON_DIR%
echo.
echo start.bat will now use this Python automatically.
echo.
pause
