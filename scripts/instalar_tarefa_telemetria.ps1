# Registra a tarefa agendada da coleta de telemetria da Gobrax.
#
# Por que existe: as funcoes sincronizar() so rodavam quando alguem abria uma
# tela com `force`. O cache ficou cinco dias parado sem ninguem notar e a Torre
# mostrava telemetria de 19/08 ao lado de posicoes ao vivo.
#
# Segue o mesmo padrao das tarefas ja instaladas (API, AutoDeploy, Tunnel):
# conta SISTEMA, para nao depender de sessao aberta.
#
# Uso (PowerShell como Administrador):
#   powershell -ExecutionPolicy Bypass -File scripts\instalar_tarefa_telemetria.ps1

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$nome = 'Cortex Sulista - Telemetria'

# Exige elevacao: Register-ScheduledTask com principal SISTEMA devolve
# "Acesso negado" cru, que nao diz o que fazer.
$admin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
  throw "Abra o PowerShell COMO ADMINISTRADOR e rode de novo (a tarefa roda como SISTEMA)."
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

Write-Host "Tarefa '$nome' registrada."
Get-ScheduledTask -TaskName $nome | Select-Object TaskName, State | Format-Table -AutoSize
