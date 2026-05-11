@echo off
cd /d "%~dp0"
set PYTHONUNBUFFERED=1

:: DeskAgent start script
:: Works for both developers (system Python) and customers (embedded Python)
:: Supports startup_mode: "foreground" (console) or "background" (no console)
::
:: Optional parameters:
::   --port <number>         HTTP server port (default: 8765)
::   --shared-dir <path>     Set DESKAGENT_SHARED_DIR (config, agents, skills)
::   --workspace-dir <path>  Set DESKAGENT_WORKSPACE_DIR (logs, exports, state)
::   --backends <path>       Path to backends.json (AI keys, overrides default)
::   --apis <path>           Path to apis.json (external APIs, overrides default)
::
:: Example:
::   start.bat --port 8766 --shared-dir "Z:\Team\AIAssistant" --workspace-dir "D:\DeskAgent"
::   start.bat --backends "C:\test\backends.json" --apis "C:\test\apis.json"

:: Note: Instance management is handled by Python (via PID file)
:: This allows multiple installations to run in parallel on different ports

:: Parse command line arguments
set DESKAGENT_PORT=
set DESKAGENT_BACKENDS=
set DESKAGENT_APIS=
:parse_args
if "%~1"=="" goto done_args
if /i "%~1"=="--port" (
    set DESKAGENT_PORT=%~2
    shift
    shift
    goto parse_args
)
if /i "%~1"=="-p" (
    set DESKAGENT_PORT=%~2
    shift
    shift
    goto parse_args
)
if /i "%~1"=="--shared-dir" (
    set DESKAGENT_SHARED_DIR=%~2
    shift
    shift
    goto parse_args
)
if /i "%~1"=="--workspace-dir" (
    set DESKAGENT_WORKSPACE_DIR=%~2
    shift
    shift
    goto parse_args
)
if /i "%~1"=="--backends" (
    set DESKAGENT_BACKENDS=%~2
    shift
    shift
    goto parse_args
)
if /i "%~1"=="--apis" (
    set DESKAGENT_APIS=%~2
    shift
    shift
    goto parse_args
)
shift
goto parse_args
:done_args

:: Build Python args
set PYTHON_ARGS=
if not "%DESKAGENT_PORT%"=="" set PYTHON_ARGS=--port %DESKAGENT_PORT%
if not "%DESKAGENT_BACKENDS%"=="" set PYTHON_ARGS=%PYTHON_ARGS% --backends "%DESKAGENT_BACKENDS%"
if not "%DESKAGENT_APIS%"=="" set PYTHON_ARGS=%PYTHON_ARGS% --apis "%DESKAGENT_APIS%"

:: Find Python executable
set PYTHON_EXE=
set PYTHONW_EXE=

if exist "python\python.exe" (
    set PYTHON_EXE="%~dp0python\python.exe"
    set PYTHONW_EXE="%~dp0python\pythonw.exe"
    set USING_EMBEDDED=1
) else (
    echo [WARNING] Embedded Python nicht gefunden in: %~dp0python\
    echo [WARNING] Nutze System-Python - fuehre setup-python.bat aus fuer konsistente Dev-Umgebung
    echo.
    set USING_EMBEDDED=0
    where py >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set PYTHON_EXE=py
        set PYTHONW_EXE=pyw
    ) else (
        where python >nul 2>&1
        if %ERRORLEVEL% equ 0 (
            set PYTHON_EXE=python
            set PYTHONW_EXE=pythonw
        )
    )
)

if "%PYTHON_EXE%"=="" (
    echo [ERROR] Python not found!
    echo.
    echo         Please install Python 3.10+ from https://python.org
    echo         Or run the installer to get embedded Python.
    echo.
    pause
    exit /b 1
)

:: Set PYTHONPATH to scripts directory (absolute path)
:: This ensures ALL imports resolve correctly regardless of CWD or import context
set PYTHONPATH=%~dp0scripts

:: Check startup_mode from config using Python
cd /d "%~dp0scripts"
for /f "tokens=*" %%i in ('%PYTHON_EXE% -c "import sys; sys.path.insert(0, '.'); from paths import load_config; c=load_config(); print(c.get('startup_mode', 'foreground'))" 2^>nul') do set STARTUP_MODE=%%i

:: Default to foreground if check failed
if "%STARTUP_MODE%"=="" set STARTUP_MODE=foreground

:: Launch based on startup_mode
if "%STARTUP_MODE%"=="background" (
    echo [INFO] Starting in background mode (no console)
    start "" %PYTHONW_EXE% -c "import sys; sys.path.insert(0, '.'); from assistant import main; main()" %PYTHON_ARGS%
    exit /b
)

:: Foreground mode (default) - with console
title AI Assistant
echo [INFO] Starting DeskAgent...
%PYTHON_EXE% -c "import sys; sys.path.insert(0, '.'); from assistant import main; main()" %PYTHON_ARGS%
if errorlevel 1 pause
exit /b
