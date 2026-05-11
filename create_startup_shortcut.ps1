$WshShell = New-Object -ComObject WScript.Shell
$StartupPath = [Environment]::GetFolderPath('Startup')
$Shortcut = $WshShell.CreateShortcut("$StartupPath\AI Assistant.lnk")
$Shortcut.TargetPath = "e:\aiassistant\autostart.bat"
$Shortcut.WorkingDirectory = "e:\aiassistant"
$Shortcut.WindowStyle = 7  # Minimized
$Shortcut.Save()
Write-Host "Shortcut created at: $StartupPath\AI Assistant.lnk"
