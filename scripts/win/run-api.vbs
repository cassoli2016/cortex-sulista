' CÓRTEX — sobe a API OCULTA (sem janela) na porta 8010, a partir do venv do projeto.
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "E:\Cortex-Sulista\cortex-sulista"
sh.Run """E:\Cortex-Sulista\cortex-sulista\.venv\Scripts\python.exe"" -m uvicorn api.main:app --host 127.0.0.1 --port 8010", 0, False
