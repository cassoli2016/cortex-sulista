# Registra a tarefa agendada da coleta de jornada da RasterJOR.
#
# Por que existe: ate agora a jornada chegava por uma rotina EXTERNA, que
# escrevia em sulista.rasterjor_* no AVA. Ela parou em 15/04/2026 e ficou 136
# dias parada - o CORTEX nao tinha como consertar nem como saber, porque o
# unico sintoma era uma tela vazia, que se le como "ninguem rodou" em vez de
# "parou de chegar". A coleta agora e nossa, e sem esta tarefa ela so rodaria
# quando alguem clicasse "Coletar agora" na tela: o mesmo problema de novo,
# com outro dono.
#
# Segue o mesmo padrao das tarefas ja instaladas (API, AutoDeploy, Tunnel,
# Telemetria, Pneus, Backup): conta SISTEMA, para nao depender de sessao
# aberta.
#
# Uso (PowerShell como Administrador). CAMINHO COMPLETO de proposito: o
# PowerShell elevado abre em C:\Windows\system32, onde o caminho relativo nao
# resolve ("O argumento ... nao existe").
#   powershell -ExecutionPolicy Bypass -File "C:\Users\inteligencia\Documents\cortex-sulista\scripts\instalar_tarefa_jornada.ps1"


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
$nome = 'Cortex Sulista - Jornada'

# AUTO-ELEVACAO, igual as demais: registrar um principal SISTEMA exige
# elevacao, sem alternativa.
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

# PYTHON DO VENV, CAMINHO ABSOLUTO. A tarefa roda como SISTEMA, que nao tem o
# PATH do usuario, e -WorkingDirectory nao chega ate o interpretador: com
# caminho relativo a tarefa tenta abrir C:\Windows\System32\scripts\... e morre
# com 0x80070002.
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "python do venv nao encontrado em $py" }
$alvo = Join-Path $repo "scripts\coletar_jornada.py"
if (-not (Test-Path $alvo)) { throw "script nao encontrado em $alvo" }

Write-Host "repo: $repo"
Write-Host "py:   $py"
Log "acao: $py $alvo"
$acao = New-ScheduledTaskAction -Execute $py `
  -Argument "`"$alvo`"" -WorkingDirectory $repo

# DUAS VEZES AO DIA, e nao de hora em hora. Tres razoes, todas medidas:
#
# 1. A API so aceita consulta RETROATIVA (D-1): pedir uma janela que alcance
#    hoje volta HTTP 400. Nao existe dado novo de hoje para buscar, entao
#    coletar de hora em hora buscaria a mesma coisa.
# 2. O relatorio de produtividade aceita UMA consulta a cada 10 minutos.
#    Agendar apertado transforma a rotina em uma fila de recusas.
# 3. A janela padrao ja e de 7 dias, de proposito: a RasterJOR corrige jornada
#    retroativamente (o RH ajusta marcacao no dia seguinte), e coletar so
#    ontem deixaria a correcao para tras para sempre.
#
# A segunda passagem existe como RETENTATIVA: se a da manha falhar por rede,
# sem ela nada tentaria de novo ate o dia seguinte - e o buraco de um dia so
# aparece quando alguem olha.
$gatilhos = @(
  (New-ScheduledTaskTrigger -Daily -At 06:20),
  (New-ScheduledTaskTrigger -Daily -At 14:20)
)

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# A coleta dos quatro recursos leva ~15 s numa janela de 7 dias. 20 min de
# teto cobre folgado, inclusive uma espera de limite de taxa, e evita tarefa
# pendurada segurando a proxima execucao.
$cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
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
Start-Sleep -Seconds 8
(Get-ScheduledTask -TaskName $nome | Get-ScheduledTaskInfo |
  Select-Object LastRunTime, LastTaskResult, NextRunTime | Format-List)
Write-Host "A trilha de cada passagem fica em jor_carga - inclusive a que"
Write-Host "falhou e a que nao trouxe nada. E dela que a Saude tira o alarme."
