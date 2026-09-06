' CORTEX - lanca o tunel Cloudflare OCULTO (cortex.cassolitech.com.br -> :8010).
'
' O cloudflared NAO mora no repositorio: ele vem do winget e fica no perfil de
' QUEM instalou. Ate 06/09/2026 este arquivo fixava "C:\Users\casso\...", o
' perfil de outra pessoa - numa maquina qualquer ele falhava calado, porque o
' wscript nao mostra janela nem erro. Agora procura, e RECLAMA quando nao acha:
' um lancador que falha em silencio custa mais que um que avisa.
'
' A config (config-cortex.yml) tambem mora no perfil de quem instalou; por isso
' ela e procurada do lado do binario e no perfil corrente.
' ASCII puro: o wscript le .vbs sem BOM como ANSI.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

perfil = sh.ExpandEnvironmentStrings("%USERPROFILE%")
exe = ""
candidatos = Array( _
  perfil & "\AppData\Local\Microsoft\WinGet\Packages\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe", _
  "C:\Program Files (x86)\cloudflared\cloudflared.exe", _
  "C:\Program Files\cloudflared\cloudflared.exe", _
  "C:\Tools\cloudflared\cloudflared.exe")
For Each c In candidatos
  If exe = "" And fso.FileExists(c) Then exe = c
Next

cfg = perfil & "\.cloudflared\config-cortex.yml"

If exe = "" Then
  MsgBox "cloudflared nao encontrado. Instale com: winget install Cloudflare.cloudflared", 16, "CORTEX"
ElseIf Not fso.FileExists(cfg) Then
  MsgBox "config-cortex.yml nao encontrado em " & cfg, 16, "CORTEX"
Else
  sh.Run """" & exe & """ tunnel --config """ & cfg & """ run cortex", 0, False
End If
