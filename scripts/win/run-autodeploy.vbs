' CORTEX - executa um ciclo de auto-deploy OCULTO (sem janela).
'
' Deriva a raiz do proprio caminho: ate 06/09/2026 fixava "E:\Cortex-Sulista\",
' que e de outra maquina. Ver o cabecalho de run-api.vbs.
' ASCII puro: o wscript le .vbs sem BOM como ANSI.
Set fso = CreateObject("Scripting.FileSystemObject")
raiz = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & raiz & "\scripts\autodeploy.ps1""", 0, False
