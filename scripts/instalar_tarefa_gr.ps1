# Registra a tarefa agendada da coleta do Gerenciamento de Risco (RasterIntegra).
#
# Por que existe: a aba "Risco por viagem" le o BANCO, nao a Raster - a tela
# abre em milissegundos e nao cai junto com o fornecedor. O preco e este: sem
# coleta o banco envelhece e a aba mostra o risco de anteontem como se fosse
# o de hoje. A trilha de cada passagem fica em gr_carga - inclusive a que
# falhou - e e dela que a Saude do Servidor tira o frescor.
#
# A coleta e POR PLACA (o unico filtro que o servidor da Raster respeita -
# medido em 01/09/2026) com pausa de 15 s entre chamadas para respeitar o
# rate-limit do fornecedor: ~80 placas por noite = ~20 minutos.
#
# HORARIO: 04:40, uma vez por dia. O consolidado so existe quando a viagem
# FINALIZA - e finalizada nao muda mais; coletar mais vezes nao torna o dado
# mais novo. A janela de 8 dias da coleta e a retentativa embutida: a noite
# que falhar e coberta pela seguinte.
#
# Segue o mesmo padrao das tarefas ja instaladas (API, AutoDeploy, Tunnel,
# Smartec, Pneus, Backup): conta SISTEMA, para nao depender de sessao aberta.
#
# Uso (PowerShell como Administrador). CAMINHO COMPLETO de proposito: o
# PowerShell elevado abre em C:\Windows\system32, onde o caminho relativo nao
# resolve ("O argumento ... nao existe").
#   powershell -ExecutionPolicy Bypass -File "C:\Users\inteligencia\Documents\cortex-sulista\scripts\instalar_tarefa_gr.ps1"


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
$nome = 'Cortex Sulista - Gerenciamento de Risco'

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
$alvo = Join-Path $repo "scripts\coletar_gr.py"
if (-not (Test-Path $alvo)) { throw "script nao encontrado em $alvo" }

Write-Host "repo: $repo"
Write-Host "py:   $py"
Log "acao: $py $alvo"
$acao = New-ScheduledTaskAction -Execute $py `
  -Argument "`"$alvo`"" -WorkingDirectory $repo

# UMA VEZ POR DIA, de madrugada. O consolidado de risco so nasce quando a
# viagem finaliza, e viagem finalizada nao muda mais - nao ha o que buscar de
# hora em hora. 04:40 deixa o dado pronto antes do primeiro cafe e fora do
# horario das outras coletas (Smartec 06:20, WhatsApp 06:45).
$gatilhos = @(
  (New-ScheduledTaskTrigger -Daily -At 04:40)
)

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# ~80 placas x 15 s de pausa = ~20 min de coleta normal. 90 min de teto
# cobre a noite de pico (mais placas, retentativa de rate-limit) sem deixar
# tarefa pendurada para sempre.
$cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 90) `
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
Write-Host "A primeira carga completa (backfill de 12 meses) roda a parte:"
Write-Host "  uv run --no-sync python scripts/coletar_gr.py --backfill"
Write-Host "A trilha de cada passagem fica em gr_carga - inclusive a que"
Write-Host "falhou e a que nao trouxe nada. E dela que a Saude tira o alarme."
