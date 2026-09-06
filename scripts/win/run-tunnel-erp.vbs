' CORTEX - mantem o tunel SSH ao ERP AVA rodando OCULTO (sem janela), via chave.
' Reconecta sozinho: o loop esta no tunel_erp.ps1.
'
' NOTA: esta instalacao NAO usa mais o tunel - o .env aponta direto para o ERP.
' O arquivo fica porque a forma de acesso pode voltar a mudar, e porque um
' lancador que aponta para o lugar errado e pior que um que nao existe.
'
' Deriva a raiz do proprio caminho (fixava "E:\Cortex-Sulista\", de outra
' maquina). ASCII puro: o wscript le .vbs sem BOM como ANSI.
Set fso = CreateObject("Scripting.FileSystemObject")
raiz = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & raiz & "\scripts\tunel_erp.ps1""", 0, False
