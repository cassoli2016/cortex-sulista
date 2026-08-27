# Registra a tarefa agendada do BACKUP do banco local do CORTEX.
#
# Por que existe: enquanto o dado morava em SQLite, backup era copiar a pasta
# data/. Com o PostgreSQL isso deixou de ser verdade - e sem esta tarefa o
# scripts/backup_cortex.ps1 vira um backup que ninguem roda, o que e pior que
# nao ter backup nenhum, porque parece que tem.
#
# Ver docs/MIGRACAO_POSTGRES.md, secao 2.
#
# Segue o mesmo padrao das tarefas ja instaladas (API, AutoDeploy, Tunnel):
# conta SISTEMA, para nao depender de sessao aberta.
#
# Uso (PowerShell como Administrador). CAMINHO COMPLETO de proposito: o
# PowerShell elevado abre em C:\Windows\system32, onde o caminho relativo nao
# resolve ("O argumento ... nao existe").
#   powershell -ExecutionPolicy Bypass -File "C:\Users\inteligencia\Documents\cortex-sulista\scripts\instalar_tarefa_backup.ps1"


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
$nome = 'Cortex Sulista - Backup'

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


# PowerShell, nao python: o backup e pg_dump.exe, e o script ja resolve
# credencial (do .env, nunca da linha de comando) e retencao.
$ps1 = Join-Path $repo "scripts\backup_cortex.ps1"
if (-not (Test-Path $ps1)) { throw "script nao encontrado em $ps1" }
Log "acao: powershell -File $ps1"
$acao = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$ps1`"" `
  -WorkingDirectory $repo

# UMA VEZ POR DIA, as 03:20 - antes da coleta de telemetria (05:30) e da de
# pneus (05:10), para o dump nao competir com elas por disco. Sem gatilho de
# -AtStartup: backup no boot atrasa a subida da API e o dado do boot e o mesmo
# do dump da madrugada.
$gatilhos = @( (New-ScheduledTaskTrigger -Daily -At 03:20) )

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# O dump atual leva menos de um segundo (11 KB); 15 min de teto e folga para o
# dia em que o banco tiver os dez stores dentro.
$cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
  -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilhos `
  -Principal $principal -Settings $cfg -Force | Out-Null

$t = Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue
if (-not $t) { throw "A tarefa NAO foi criada. Nada foi registrado." }
Log "tarefa '$nome' registrada com sucesso"
Write-Host ""
Write-Host "OK: tarefa '$nome' registrada." -ForegroundColor Green
$t | Select-Object TaskName, State, @{n='Conta';e={$_.Principal.UserId}} | Format-Table -AutoSize
Write-Host ""
Write-Host "Rodando o primeiro backup agora para validar..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $nome
Start-Sleep -Seconds 8
(Get-ScheduledTask -TaskName $nome | Get-ScheduledTaskInfo |
  Select-Object LastRunTime, LastTaskResult, NextRunTime | Format-List)
Write-Host "Conferindo o que ficou em data\backup:"
& powershell -NoProfile -ExecutionPolicy Bypass -File $ps1 -Conferir
