Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c """ & WshShell.ExpandEnvironmentStrings("%USERPROFILE%") & "\OneDrive\デスクトップ\UTAMEMO\training\autostart_agent.bat""", 7, False
