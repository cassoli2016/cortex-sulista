' CÓRTEX — lança o túnel Cloudflare OCULTO (cortex.cassolitech.com.br -> localhost:8010).
Set sh = CreateObject("WScript.Shell")
sh.Run """C:\Users\casso\AppData\Local\Microsoft\WinGet\Packages\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe"" tunnel --config ""C:\Users\casso\.cloudflared\config-cortex.yml"" run cortex", 0, False
