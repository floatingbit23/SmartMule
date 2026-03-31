Set WshShell = CreateObject("WScript.Shell")
' El parámetro 0 oculta la ventana de la consola
WshShell.Run "pythonw.exe main.py start", 0
Set WshShell = Nothing
