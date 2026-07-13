' CÓRTEX — mantém o túnel SSH ao ERP AVA rodando OCULTO (sem janela), via chave.
' Reconecta sozinho: o loop está no tunel_erp.ps1.
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""E:\Cortex-Sulista\cortex-sulista\scripts\tunel_erp.ps1""", 0, False
