Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "c:\Users\Mazonia\Desktop\XAUUSD-AI-Trading-Bot"
WshShell.Run "cmd.exe /c run_standby.bat", 0, False
