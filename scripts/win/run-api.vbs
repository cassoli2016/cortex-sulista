' CORTEX - sobe a API OCULTA (sem janela) na porta 8010, a partir do venv do projeto.
'
' ESTE E O LANCADOR DE REFERENCIA, versionado. O que a tarefa do Windows executa
' de fato e uma copia em data\win\, que NAO e versionada (o .gitignore tira
' data/*). Ate 06/09/2026 este arquivo apontava para "E:\Cortex-Sulista\...",
' caminho de OUTRA maquina: quem o usasse subiria a API do lugar errado, ou nao
' subiria. Agora ele deriva a raiz do proprio caminho e serve em qualquer
' instalacao.
'
' WEB_CONCURRENCY: uma variavel para DUAS coisas, de proposito. O uvicorn a usa
' como padrao de --workers, e o api/processos.py a le para dimensionar os pools
' (20/4 -> 6 no banco da casa, 16/4 -> 6 no ERP; o piso e o maior leque de uma
' requisicao so, que e 5, da Visao Geral) e para saber que a eleicao de lider do
' api/lider.py e obrigatoria. Passar --workers 4 na linha de comando SEM exportar
' a variavel criaria duas fontes: os pools ficariam dimensionados para 1 processo
' e o PostgreSQL local (max_connections=100) recusaria conexao.
'
' Sem a eleicao, cada worker sobe o relogio do aviso de carga e o cliente recebe
' a mesma mensagem uma vez por worker. Medido: o startup roda 4 a 6 vezes com
' --workers 4 (o uvicorn respawna worker no Windows).
'
' ASCII PURO E SEM ACENTO, pelo mesmo motivo dos .ps1 da casa: o wscript le um
' .vbs sem BOM usando a codepage ANSI do sistema.
Set fso = CreateObject("Scripting.FileSystemObject")
raiz = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
Set sh = CreateObject("WScript.Shell")
sh.Environment("PROCESS")("WEB_CONCURRENCY") = "4"
sh.CurrentDirectory = raiz
sh.Run """" & raiz & "\.venv\Scripts\python.exe"" -m uvicorn api.main:app --host 127.0.0.1 --port 8010", 0, False
