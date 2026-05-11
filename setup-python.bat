@echo off
echo ========================================
echo DeskAgent - Python Setup
echo ========================================

:: Python-Version aus zentraler Datei lesen (python-version.txt)
:: WICHTIG: Python 3.12 verwenden - spacy/thinc ist noch nicht mit 3.13 kompatibel!
set /p PYTHON_VERSION=<"%~dp0python-version.txt"
set PYTHON_DIR=%~dp0python
echo Using Python %PYTHON_VERSION%

:: --force or --reinstall: wipe existing python/ before installing
set FORCE_REINSTALL=0
if /i "%~1"=="--force" set FORCE_REINSTALL=1
if /i "%~1"=="--reinstall" set FORCE_REINSTALL=1

if exist "%PYTHON_DIR%\python.exe" (
    if "%FORCE_REINSTALL%"=="1" (
        echo Force reinstall - stopping any running DeskAgent processes...
        :: Kill python/pythonw processes that are using our embedded Python.
        :: We only kill those whose path starts with our PYTHON_DIR to avoid
        :: nuking unrelated Python apps on the user's machine.
        for /f "tokens=2 delims=," %%i in ('wmic process where "executablepath like '%PYTHON_DIR:\=\\%\\%%'" get processid /format:csv 2^>nul ^| findstr /r "[0-9]"') do (
            echo   killing PID %%i
            taskkill /F /PID %%i >nul 2>&1
        )
        :: Give Windows a moment to release file locks
        timeout /t 2 /nobreak >nul

        echo Force reinstall - removing existing python/ directory...
        :: Atomic-ish replace: rename first, then delete the renamed dir.
        :: This catches "directory locked" failures clearly before we start
        :: extracting fresh files on top of half-deleted ones.
        if exist "%PYTHON_DIR%.old" rmdir /s /q "%PYTHON_DIR%.old" >nul 2>&1
        ren "%PYTHON_DIR%" "python.old"
        if errorlevel 1 (
            echo [ERROR] Cannot rename %PYTHON_DIR% - files are still locked.
            echo         Close DeskAgent completely (check Task Manager for
            echo         python.exe / pythonw.exe processes) and try again.
            pause
            exit /b 1
        )
        rmdir /s /q "%PYTHON_DIR%.old" >nul 2>&1
        goto :do_install
    )

    :: Verify existing install matches expected version
    for /f "tokens=2" %%v in ('"%PYTHON_DIR%\python.exe" --version 2^>^&1') do set CURRENT_VER=%%v
    if not "%CURRENT_VER%"=="%PYTHON_VERSION%" (
        echo [ERROR] Python version mismatch in %PYTHON_DIR%
        echo         Expected: %PYTHON_VERSION%
        echo         Found:    %CURRENT_VER%
        echo.
        echo Run "setup-python.bat --force" to wipe and reinstall,
        echo or manually delete %PYTHON_DIR% first.
        pause
        exit /b 1
    )

    :: Verify sqlite3 works (the canonical "is this install healthy" check)
    "%PYTHON_DIR%\python.exe" -c "import sqlite3" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python install is corrupt - sqlite3 import failed.
        echo         This usually means _sqlite3.pyd / sqlite3.dll were
        echo         replaced with files from a different Python version.
        echo.
        echo Run "setup-python.bat --force" to wipe and reinstall.
        pause
        exit /b 1
    )

    echo Python bereits vorhanden und gesund: %PYTHON_DIR% (%CURRENT_VER%)
    echo Zum Neuinstallieren: setup-python.bat --force
    pause
    exit /b 0
)

:do_install
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
:: CRITICAL: only copy from a Python with MATCHING major.minor version!
:: A 3.13 _sqlite3.pyd in a 3.12 embedded bundle is the #1 cause of
:: "ImportError: DLL load failed while importing _sqlite3" reports.
::
:: PYTHON_VERSION is e.g. "3.12.8" - extract the "3.12" major.minor part.
for /f "tokens=1,2 delims=." %%a in ("%PYTHON_VERSION%") do (
    set TARGET_MAJ=%%a
    set TARGET_MIN=%%b
)
set TARGET_MAJMIN=%TARGET_MAJ%.%TARGET_MIN%

:: Use the py launcher with explicit version selector first (most reliable)
:: e.g. "py -3.12 ..." picks ONLY a 3.12 install, never 3.13.
for /f "delims=" %%p in ('py -%TARGET_MAJMIN% -c "import sys; print(sys.prefix)" 2^>nul') do (
    if exist "%%p\DLLs\_sqlite3.pyd" (
        copy /Y "%%p\DLLs\_sqlite3.pyd" "%PYTHON_DIR%\" >nul 2>&1
        copy /Y "%%p\DLLs\sqlite3.dll" "%PYTHON_DIR%\" >nul 2>&1
        echo       sqlite3 DLLs copied from: %%p\DLLs (py -%TARGET_MAJMIN%)
    )
)

:: Fallback: untargeted py -3 only if version-locked lookup didn't find anything.
:: This is the OLD behavior and CAN cause version mismatches - verify before using.
if not exist "%PYTHON_DIR%\_sqlite3.pyd" (
    for /f "delims=" %%p in ('py -3 -c "import sys; print(sys.prefix)" 2^>nul') do (
        if exist "%%p\DLLs\_sqlite3.pyd" (
            :: Check that the source Python's version matches our target
            for /f "tokens=2" %%v in ('"%%p\python.exe" --version 2^>^&1') do set SRC_VER=%%v
            for /f "tokens=1,2 delims=." %%a in ("!SRC_VER!") do (
                if "%%a.%%b"=="%TARGET_MAJMIN%" (
                    copy /Y "%%p\DLLs\_sqlite3.pyd" "%PYTHON_DIR%\" >nul 2>&1
                    copy /Y "%%p\DLLs\sqlite3.dll" "%PYTHON_DIR%\" >nul 2>&1
                    echo       sqlite3 DLLs copied from: %%p\DLLs (verified %TARGET_MAJMIN%)
                ) else (
                    echo       SKIPPED %%p\DLLs - version mismatch ^(found !SRC_VER!, need %TARGET_MAJMIN%.x^)
                )
            )
        )
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

:: Verify sqlite3 - runtime test, not just file-existence
echo       [Verify] Testing sqlite3 import...
"%PYTHON_DIR%\python.exe" -c "import sqlite3; sqlite3.connect(':memory:').close()" >nul 2>&1
if errorlevel 1 (
    echo       [ERROR] sqlite3 import FAILED at runtime.
    echo               Most common cause: _sqlite3.pyd and sqlite3.dll were
    echo               copied from a different Python version (e.g. 3.13 files
    echo               in a 3.12 install).
    echo.
    echo               Check the [Stdlib] step above for any "version mismatch"
    echo               warnings. To fix, either install Python %TARGET_MAJMIN%
    echo               on the system, or delete deskagent\python\ and re-run
    echo               setup-python.bat.
    echo.
    pause
    exit /b 1
)
echo       sqlite3: OK

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
