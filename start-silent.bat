@echo off
:: DeskAgent - Start without console window
:: Uses pythonw.exe for windowless operation

cd /d "%~dp0"

:: Option 1: Embedded Python in parent folder (customer installation)
if exist "..\python\pythonw.exe" (
    cd /d "%~dp0scripts"
    start "" "%~dp0..\python\pythonw.exe" -c "import sys; sys.path.insert(0, '.'); from assistant import main; main()"
    exit /b
)

:: Option 2: System Python (developer) - use pythonw
where pythonw >nul 2>&1
if %ERRORLEVEL% equ 0 (
    cd /d "%~dp0scripts"
    start "" pythonw -c "import sys; sys.path.insert(0, '.'); from assistant import main; main()"
    exit /b
)

:: Fallback: No pythonw available, use regular python
echo [INFO] pythonw not found, using regular python (console will show)
call "%~dp0start.bat"
