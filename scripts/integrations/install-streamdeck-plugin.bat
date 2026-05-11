@echo off
echo Installing DeskAgent Stream Deck Plugin...

set "SOURCE=%~dp0integrations\streamdeck-plugin\com.deskagent.cli.sdPlugin"
set "TARGET=%APPDATA%\Elgato\StreamDeck\Plugins\com.deskagent.cli.sdPlugin"

:: Remove old version
if exist "%TARGET%" rmdir /s /q "%TARGET%"

:: Copy plugin
xcopy "%SOURCE%" "%TARGET%" /E /I /Y

echo.
echo Plugin installed!
echo Please restart Stream Deck software.
echo.
pause
