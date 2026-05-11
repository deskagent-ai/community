@echo off
setlocal EnableDelayedExpansion
title DeskAgent - Update
cd /d "%~dp0.."
set PROJECT_DIR=%CD%

echo.
echo ============================================================
echo   DeskAgent - Update
echo ============================================================
echo.

:: Check for git (embedded or system)
if exist "git\cmd\git.exe" (
    set GIT_EXE=git\cmd\git.exe
) else if exist ".repo\.git" (
    :: Customer installation with .repo folder
    cd /d "%PROJECT_DIR%\.repo"
    if exist "%PROJECT_DIR%\git\cmd\git.exe" (
        set GIT_EXE=%PROJECT_DIR%\git\cmd\git.exe
    ) else (
        where git >nul 2>&1
        if %ERRORLEVEL% equ 0 (
            set GIT_EXE=git
        ) else (
            echo [ERROR] Git not found!
            pause
            exit /b 1
        )
    )
    echo [1/3] Pulling latest changes...
    "%GIT_EXE%" -c credential.helper= pull origin main
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Git pull failed!
        pause
        exit /b 1
    )
    echo [2/3] Copying updated files...
    xcopy /E /I /Y /Q "%PROJECT_DIR%\.repo\deskagent" "%PROJECT_DIR%\deskagent" >nul

    echo [3/3] Checking for new dependencies...
    if exist "%PROJECT_DIR%\python\python.exe" (
        if exist "%PROJECT_DIR%\deskagent\requirements.txt" (
            "%PROJECT_DIR%\python\python.exe" -m pip install -r "%PROJECT_DIR%\deskagent\requirements.txt" --no-warn-script-location -q
            if !ERRORLEVEL! equ 0 (
                echo       Dependencies up to date.
            ) else (
                echo       [WARNING] Some dependencies may have failed.
            )
        )
    ) else (
        echo       Skipped (no embedded Python)
    )
    echo.
    echo Update complete!
    pause
    exit /b
) else (
    :: Developer installation (direct repo)
    where git >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set GIT_EXE=git
    ) else (
        echo [ERROR] Git not found!
        pause
        exit /b 1
    )
)

:: Developer: Direct git pull
echo [1/1] Pulling latest changes...
"%GIT_EXE%" pull
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Git pull failed!
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Update Complete!
echo ============================================================
echo.
echo   Run deskagent\start.bat to launch DeskAgent.
echo.
pause
