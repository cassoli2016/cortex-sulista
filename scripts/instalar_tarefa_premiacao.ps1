# Registra a tarefa agendada da coleta da nota da Gobrax (premiacao).
#
# Por que existe: ate 18/09/2026 a coleta da Gobrax era um EFEITO COLATERAL de
# alguem abrir a tela da premiacao antiga. Com as abas daquele modelo fora do
# ar, ninguem mais chama aquela rota - e o pilar de CONDUCAO da Gestao de
# Motoristas congelaria no ultimo snapshot que alguem pediu por acaso.
#
# A falha seria MUDA: a nota nao some da tela, ela para de mudar; ou o ciclo
# novo nasce "sem leitura da Gobrax" e a nota composta se renormaliza entre os
# outros dois pilares, em silencio, para a frota inteira.
#
# HORARIO: 04:20, uma vez por dia, antes da coleta do GR (04:40). O mes
# corrente e o unico que muda; mes fechado so se recoleta com --force, porque
# reescrever um mes ja pago e o defeito que o fechamento existe para impedir.
#
# Uso (PowerShell como Administrador). CAMINHO COMPLETO de proposito: o
# PowerShell elevado abre em C:\Windows\system32, onde o caminho relativo nao
# resolve ("O argumento ... nao existe").
#   powershell -ExecutionPolicy Bypass -File "C:\Users\inteligencia\Documents\cortex-sulista\scripts\instalar_tarefa_premiacao.ps1"


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
$nome = 'Cortex Sulista - Premiacao (nota Gobrax)'

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
$alvo = Join-Path $repo "scripts\coletar_premiacao.py"
if (-not (Test-Path $alvo)) { throw "script nao encontrado em $alvo" }

Write-Host "repo: $repo"
Write-Host "py:   $py"
Log "acao: $py $alvo"
$acao = New-ScheduledTaskAction -Execute $py `
  -Argument "`"$alvo`"" -WorkingDirectory $repo

# UMA VEZ POR DIA, de madrugada. A nota da Gobrax e MENSAL: ela se move ao
# longo do mes corrente e para de se mover quando o mes fecha - nao ha o que
# buscar de hora em hora. 04:20 deixa o dado pronto antes do GR (04:40) e do
# primeiro cafe.
$gatilhos = @(
  (New-ScheduledTaskTrigger -Daily -At 04:20)
)

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# A coleta e UMA chamada ao fornecedor pelo mes inteiro: segundos no dia bom.
# 20 min de teto cobrem a Gobrax lenta sem deixar tarefa pendurada.
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
Write-Host "Para coletar um mes especifico agora:"
Write-Host "  uv run --no-sync python scripts/coletar_premiacao.py --mes 2026-09"
Write-Host "O snapshot fica em data/premiacao/ - e dele que sai o pilar de"
Write-Host "conducao da Gestao de Motoristas."
