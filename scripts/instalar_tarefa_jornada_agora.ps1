# Registra a tarefa de coleta em TEMPO REAL da jornada (painel de TV).
#
# POR QUE ELA E SEPARADA da tarefa 'Cortex Sulista - Jornada', que ja existe e
# roda duas vezes ao dia:
#
# /external-api/vehicles/ e o UNICO recurso da RasterJOR que responde AGORA -
# evento atual por veiculo, ha quanto tempo, e a posicao (mediana de 4 minutos
# de idade). Todo o resto da API e D-1 por regra do fornecedor: pedir uma
# janela que alcance hoje volta HTTP 400. Ou seja, ler o resto de cinco em
# cinco minutos seria bater no fornecedor 288 vezes por dia para reler o mesmo
# ontem.
#
# E o contrario tambem vale, e foi o que motivou esta tarefa: o painel de TV
# mede frescor em 30 minutos. Alimentado pela cadencia de 12 horas ele nao
# ficaria desatualizado - ficaria VAZIO, mostrando zero veiculos reportando.
#
# CINCO MINUTOS NAO E ESCOLHA NOSSA: o proprio endpoint recusa consulta mais
# frequente, com HTTP 400 e "Faltam 5 minutos para fazer outra consulta".
# Agendar mais apertado transformaria a rotina numa fila de recusas.
#
# Uso (PowerShell como Administrador). CAMINHO COMPLETO de proposito: a janela
# elevada abre em C:\Windows\system32, onde o relativo nao resolve.
#   powershell -ExecutionPolicy Bypass -File "C:\Users\inteligencia\Documents\cortex-sulista\scripts\instalar_tarefa_jornada_agora.ps1"

$ErrorActionPreference = 'Stop'

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
$nome = 'Cortex Sulista - Jornada Tempo Real'

$admin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
  Log "sem privilegio de administrador - pedindo elevacao via UAC"
  try {
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList @(
      '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
  } catch {
    throw ("Elevacao recusada. Abra o PowerShell COMO ADMINISTRADOR e rode:`n" +
           "  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`"")
  }
  return
}

# PYTHON DO VENV, CAMINHO ABSOLUTO: a tarefa roda como SISTEMA, que nao tem o
# PATH do usuario, e -WorkingDirectory nao chega ate o interpretador.
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "python do venv nao encontrado em $py" }
$alvo = Join-Path $repo "scripts\coletar_jornada.py"
if (-not (Test-Path $alvo)) { throw "script nao encontrado em $alvo" }

Write-Host "repo: $repo"
Log "acao: $py $alvo --agora"
$acao = New-ScheduledTaskAction -Execute $py `
  -Argument "`"$alvo`" --agora" -WorkingDirectory $repo

# DE 5 EM 5 MINUTOS, O DIA INTEIRO. Roda tambem de madrugada de proposito: a
# operacao e 24 h e o motorista que estoura a direcao continua as 3 da manha e
# exatamente o que ninguem esta olhando.
$gatilho = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
  -RepetitionInterval (New-TimeSpan -Minutes 5)

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# UMA chamada, ~6 s medidos. O teto de 4 minutos e menor que o intervalo de
# propositO: passagem pendurada nao pode alcancar a proxima, e IgnoreNew
# garante que, se alcancar, a nova e descartada em vez de empilhar.
$cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 4) `
  -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho `
  -Principal $principal -Settings $cfg -Force | Out-Null

$t = Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue
if (-not $t) { throw "A tarefa NAO foi criada. Nada foi registrado." }
Log "tarefa '$nome' registrada com sucesso"
Write-Host ""
Write-Host "OK: tarefa '$nome' registrada." -ForegroundColor Green
$t | Select-Object TaskName, State, @{n='Conta';e={$_.Principal.UserId}} | Format-Table -AutoSize
Write-Host ""
Write-Host "Rodando a primeira passagem agora para validar..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $nome
Start-Sleep -Seconds 12
(Get-ScheduledTask -TaskName $nome | Get-ScheduledTaskInfo |
  Select-Object LastRunTime, LastTaskResult, NextRunTime | Format-List)
Write-Host "Sem esta tarefa o painel de TV da jornada fica VAZIO: a regua de"
Write-Host "frescor dele e de 30 minutos, e a coleta normal roda 2x ao dia."
