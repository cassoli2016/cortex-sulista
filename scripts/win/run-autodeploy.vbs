' CÓRTEX — executa um ciclo de auto-deploy OCULTO (sem janela).
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""E:\Cortex-Sulista\cortex-sulista\scripts\autodeploy.ps1""", 0, False
