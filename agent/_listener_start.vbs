Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Administrator\Documents\Default Project\ARIS"
WshShell.Run """C:\Program Files\Python312\python.exe"" ""C:\Users\Administrator\Documents\Default Project\ARIS\agent\pc_listener.py""", 0, False
