# Registra a tarefa agendada da coleta de telemetria da Gobrax.
#
# Por que existe: as funcoes sincronizar() so rodavam quando alguem abria uma
# tela com `force`. O cache ficou cinco dias parado sem ninguem notar e a Torre
# mostrava telemetria de 19/08 ao lado de posicoes ao vivo.
#
# Segue o mesmo padrao das tarefas ja instaladas (API, AutoDeploy, Tunnel):
# conta SISTEMA, para nao depender de sessao aberta.
#
# Uso (PowerShell como Administrador). CAMINHO COMPLETO de proposito: o
# PowerShell elevado abre em C:\Windows\system32, onde o caminho relativo nao
# resolve ("O argumento ... nao existe").
#   powershell -ExecutionPolicy Bypass -File "C:\Users\inteligencia\Documents\cortex-sulista\scripts\instalar_tarefa_telemetria.ps1"


$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$nome = 'Cortex Sulista - Telemetria'

# AUTO-ELEVACAO. As tres tarefas ja instaladas rodam como SISTEMA e o registro
# de um principal SISTEMA exige elevacao, sem alternativa. Antes o script so
# reclamava, e a mensagem se parecia com um erro qualquer no meio da saida -
# a instalacao "foi feita" duas vezes sem a tarefa existir. Agora ele mesmo
# chama o UAC: basta rodar de qualquer janela e confirmar.
$admin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
  Write-Host "Sem privilegio de administrador - pedindo elevacao (confirme no aviso do Windows)..."
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

# 3 em 3 horas: a Gobrax agrega por dia, entao coletar de hora em hora so
# gastaria chamada de API sem trazer numero novo; e um dia inteiro parado
# (que era o caso) deixa a Torre com dado velho demais para decidir.
$acao = New-ScheduledTaskAction -Execute $uv `
  -Argument "run python scripts\coletar_telemetria.py" -WorkingDirectory $repo

$gatilhos = @(
  (New-ScheduledTaskTrigger -Daily -At 05:30),
  (New-ScheduledTaskTrigger -AtStartup)
)
# repeticao a cada 3h dentro do dia
$gatilhos[0].Repetition = (New-ScheduledTaskTrigger -Once -At 05:30 `
  -RepetitionInterval (New-TimeSpan -Hours 3) `
  -RepetitionDuration (New-TimeSpan -Hours 23)).Repetition

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# A coleta leva ~70 s por competencia e sao quatro chamadas; 30 min de teto
# cobre folgado e evita tarefa pendurada segurando a proxima execucao.
$cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
  -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilhos `
  -Principal $principal -Settings $cfg -Force | Out-Null

$t = Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue
if (-not $t) { throw "A tarefa NAO foi criada. Nada foi registrado." }
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
