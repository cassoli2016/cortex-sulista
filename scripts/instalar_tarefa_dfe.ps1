# Registra a tarefa agendada da RECOLHA DE DFe na SEFAZ - as notas emitidas
# contra a Sulista, e os eventos delas.
#
# Por que existe: a nota de entrada chega hoje por e-mail do fornecedor,
# quando chega. O servico nacional de Distribuicao de DFe entrega ao
# destinatario tudo que foi emitido contra o CNPJ dele, e o XML autorizado e
# a obrigacao de guarda de cinco anos.
#
# HORARIO: de 2 em 2 horas, das 07h as 19h. NAO e de hora em hora, e a razao e
# medida: a SEFAZ FREIA consulta repetida sem resultado (cStat 656, cerca de
# 1 h de castigo por CNPJ), e na maioria das passagens nao ha nota nova. O
# proprio script tem freio proprio, entao uma passagem a mais nao machuca -
# mas tambem nao adianta nada.
#
# De madrugada nao roda: nota de fornecedor e emitida em horario comercial, e
# uma varredura as 3h so gastaria a cota do dia seguinte.
#
# Segue o mesmo padrao das tarefas ja instaladas (API, AutoDeploy, Tunnel,
# Smartec, Pneus, Backup, Monkey): conta SISTEMA, para nao depender de sessao
# aberta.
#
# Uso (PowerShell como Administrador). CAMINHO COMPLETO de proposito: o
# PowerShell elevado abre em C:\Windows\system32, onde o caminho relativo nao
# resolve ("O argumento ... nao existe").
#   powershell -ExecutionPolicy Bypass -File "C:\Users\inteligencia\Documents\cortex-sulista\scripts\instalar_tarefa_dfe.ps1"


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
$nome = 'Cortex Sulista - DFe SEFAZ'

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
$alvo = Join-Path $repo "scripts\coletar_dfe.py"
if (-not (Test-Path $alvo)) { throw "script nao encontrado em $alvo" }

Write-Host "repo: $repo"
Write-Host "py:   $py"
Log "acao: $py $alvo"
$acao = New-ScheduledTaskAction -Execute $py `
  -Argument "`"$alvo`"" -WorkingDirectory $repo

# De 2 em 2 horas das 07h as 19h. Ver o comentario do topo: a SEFAZ freia
# consulta repetida sem resultado, e passagem que nao traz nada so gasta cota.
$gatilhos = @(
  (New-ScheduledTaskTrigger -Daily -At 07:10),
  (New-ScheduledTaskTrigger -Daily -At 09:10),
  (New-ScheduledTaskTrigger -Daily -At 11:10),
  (New-ScheduledTaskTrigger -Daily -At 13:10),
  (New-ScheduledTaskTrigger -Daily -At 15:10),
  (New-ScheduledTaskTrigger -Daily -At 17:10),
  (New-ScheduledTaskTrigger -Daily -At 19:10)
)

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# Dez caixas, cada uma com teto de 40 lotes. A PRIMEIRA carga e a longa (o
# historico que a SEFAZ ainda guarda, cerca de tres meses); as seguintes
# terminam em segundos. 45 min cobre a primeira com folga.
$cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 45) `
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
Write-Host "Filial sem certificado A1 no cofre e PULADA com aviso - ela nao"
Write-Host "derruba a recolha das outras nove."
