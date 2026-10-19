$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("C:\Users\JOSEPH\Desktop\Bugema Gym Tracker.lnk")
$pythonw = (Get-Command pythonw.exe).Source
$Shortcut.TargetPath = $pythonw
$Shortcut.Arguments = """C:\Users\JOSEPH\Documents\bugema-gym-tracker-main\bugema-gym-tracker-main\app_gui.py"""
$Shortcut.WorkingDirectory = "C:\Users\JOSEPH\Documents\bugema-gym-tracker-main\bugema-gym-tracker-main"
$Shortcut.Description = "Bugema University Gym - Reception Desktop Tracker"
$Shortcut.IconLocation = "$pythonw,0"
$Shortcut.Save()
Write-Host "Desktop shortcut created successfully at: C:\Users\JOSEPH\Desktop\Bugema Gym Tracker.lnk"
