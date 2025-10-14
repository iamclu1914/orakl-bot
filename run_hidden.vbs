Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d ""C:\ORAKL Bot"" && python main.py", 0, False
Set WshShell = Nothing
