# Tarefa agendada: AVISO HORARIO DAS CARGAS por WhatsApp.
#
# Quem se inscreveu na pagina publica de rastreio recebe, de hora em hora, como
# esta a carga dele — enquanto ela estiver em viagem. A entrega encerra a
# inscricao, e mensagem IGUAL a anterior nao e reenviada: caminhao parado
# geraria a mesma frase 24 vezes por dia, a pessoa bloquearia o numero, e o
# estrago nao seria essa mensagem — seria a reputacao do numero que atende
# todos os outros clientes.
#
# ANTES DE REGISTRAR, rode o ensaio e LEIA os textos:
#   uv run python scripts/avisar_cargas.py --ensaio
# Ele monta as mensagens e nao envia nada.
#
# Uso (PowerShell). CAMINHO COMPLETO de proposito: o PowerShell elevado abre
# em system32, onde o caminho relativo nao resolve.
#   powershell -ExecutionPolicy Bypass -File "<repo>\scripts\instalar_tarefa_avisocargas.ps1"

$ErrorActionPreference = 'Stop'

# LOG EM ARQUIVO. A janela elevada e outra janela: se o script falha nela, o
# erro morre junto com ela quando fecha, e do lado de ca so se ve "nao
# registrou" sem nenhuma pista. O arquivo sobrevive.
$logDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$logFile = Join-Path $logDir 'instalar-tarefas.log'
function Log([string]$m) {
  $linha = "{0}  [{1}]  {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),
           (Split-Path -Leaf $PSCommandPath), $m
  Add-Content -Path $logFile -Value $linha -Encoding utf8
  Write-Host $m
}
Log "----- inicio -----"
trap {
  Log ("ERRO: " + $_.Exception.Message)
  Log ("  em: " + $_.InvocationInfo.PositionMessage -replace "`r?`n", ' ')
  Log "----- fim (com erro) -----"
  Write-Host ""
  Write-Host "Falhou. O detalhe ficou em: $logFile" -ForegroundColor Red
  Write-Host "Esta janela NAO vai fechar sozinha - leia a mensagem acima."
  break
}

$repo = Split-Path -Parent $PSScriptRoot
$nome = 'Cortex Sulista - Aviso de Cargas'

# AUTO-ELEVACAO. As tres tarefas ja instaladas rodam como SISTEMA e o registro
# de um principal SISTEMA exige elevacao, sem alternativa. Antes o script so
# reclamava, e a mensagem se parecia com um erro qualquer no meio da saida -
# a instalacao "foi feita" duas vezes sem a tarefa existir. Agora ele mesmo
# chama o UAC: basta rodar de qualquer janela e confirmar.
$admin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
  Log "sem privilegio de administrador - pedindo elevacao via UAC"
  try {
    # -NoExit mantem a janela elevada aberta para a confirmacao ficar visivel:
    # elevada e fechando sozinha, ninguem ve se deu certo ou nao.
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList @(
      '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
  } catch {
    throw ("Elevacao recusada. Abra o PowerShell COMO ADMINISTRADOR e rode:`n" +
           "  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`"")
  }
  return
}

# CAMINHO ABSOLUTO do uv, com a MESMA busca do autodeploy.ps1: a tarefa roda
# como SISTEMA, que nao tem o PATH do usuario. Resolver so por Get-Command
# daria um caminho que existe para quem instala e nao para quem executa.
$uv = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe"
if (-not (Test-Path $uv)) {
  $alt = Get-ChildItem 'C:\Users\*\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_*\uv.exe' -ErrorAction SilentlyContinue |
         Select-Object -First 1
  if ($alt) { $uv = $alt.FullName }
}
if (-not (Test-Path $uv)) {
  $g = (Get-Command uv -ErrorAction SilentlyContinue).Source
  if ($g) { $uv = $g }
}
if (-not (Test-Path $uv)) { throw "uv nao encontrado. Instale ou ajuste o PATH." }

Write-Host "repo: $repo"
Write-Host "uv:   $uv"

# DE 20 EM 20 MINUTOS, e a razao e a cota da Prolog. Cada execucao avanca 8
# paginas de 100; sao ~86 paginas para varrer as quatro filiais, ou seja 11
# execucoes para fechar uma volta - cerca de 4 horas. Coletar mais rapido
# esbarra no 429 e derruba a integracao inteira; mais devagar deixa o retrato
# velho demais para decidir troca de pneu.
# PYTHON DO VENV, CAMINHO ABSOLUTO. Antes era `uv run python
# scripts\avisar_cargas.py` com -WorkingDirectory, e o caminho relativo NAO
# resolvia: a tarefa tentava abrir C:\Windows\System32\scripts\avisar_cargas.py
# e morria com 0x80070002 (arquivo nao encontrado). O -WorkingDirectory
# nao chega ate o interpretador.
#
# A tarefa da API, que funciona ha meses, ja chama o python do venv
# direto ? e assim some tambem a dependencia de o `uv` estar no perfil
# de um usuario especifico.
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "python do venv nao encontrado em $py" }
$alvo = Join-Path $repo "scripts\avisar_cargas.py"
if (-not (Test-Path $alvo)) { throw "script nao encontrado em $alvo" }
Log "acao: $py $alvo"
$acao = New-ScheduledTaskAction -Execute $py `
  -Argument "`"$alvo`"" -WorkingDirectory $repo

# DE HORA EM HORA, das 06h as 21h. Nao e 24h de proposito: ninguem quer
# receber aviso de carga as 3 da manha, e a mensagem que acorda a pessoa e a
# que faz ela bloquear o numero da empresa. Quem precisar do dado de
# madrugada abre a pagina, que responde a qualquer hora.
$gatilhos = @( (New-ScheduledTaskTrigger -Daily -At 06:00) )
$gatilhos[0].Repetition = (New-ScheduledTaskTrigger -Once -At 06:00 `
  -RepetitionInterval (New-TimeSpan -Hours 1) `
  -RepetitionDuration (New-TimeSpan -Hours 15)).Repetition

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# O envio e rapido (uma consulta por inscricao ativa), mas o teto existe para
# a tarefa nao ficar pendurada num dia ruim do ERP e segurar a proxima hora.
$cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
  -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilhos `
  -Principal $principal -Settings $cfg -Force | Out-Null

$t = Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue
if (-not $t) { throw "A tarefa NAO foi criada. Nada foi registrado." }
Log "tarefa '$nome' registrada com sucesso"
Write-Host ""
Write-Host "OK: tarefa '$nome' registrada." -ForegroundColor Green
$t | Select-Object TaskName, State, @{n='Conta';e={$_.Principal.UserId}} | Format-Table -AutoSize
Write-Host "Confira na tela Saude do Servidor: ela deve sair de 'nao registrada'."
Write-Host ""
Write-Host "Rodando a primeira coleta agora para validar..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $nome
Start-Sleep -Seconds 5
(Get-ScheduledTask -TaskName $nome | Get-ScheduledTaskInfo |
  Select-Object LastRunTime, LastTaskResult, NextRunTime | Format-List)
