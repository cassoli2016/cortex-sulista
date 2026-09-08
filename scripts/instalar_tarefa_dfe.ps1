# Registra a tarefa agendada da RECOLHA DE DFe na SEFAZ - as notas emitidas
# contra a Sulista, e os eventos delas.
#
# Por que existe: a nota de entrada chega hoje por e-mail do fornecedor,
# quando chega. O servico nacional de Distribuicao de DFe entrega ao
# destinatario tudo que foi emitido contra o CNPJ dele, e o XML autorizado e
# a obrigacao de guarda de cinco anos.
#
# HORARIO: de 20 em 20 minutos, das 06h as 20h.
#
# PARECE agressivo e NAO E, porque a SEFAZ nao limita por TEMPO - ela pune
# consulta SEM RESULTADO (cStat 656, ~1 h de castigo por CNPJ). Quando vem
# documento, pode continuar na hora: e assim que se drena uma fila.
#
# E o freio esta no SCRIPT, nao no relogio da tarefa. Ele so trava depois de um
# 137 ("nada novo"), e por 65 minutos. Entao das passagens de 20 em 20 minutos:
#
#   - a que encontra documento  -> recolhe e NAO trava (o cStat foi 138)
#   - a seguinte, se nao ha nada -> ouve 137 uma vez e trava por 65 min
#   - as tres seguintes          -> nem saem: o freio as barra ANTES da chamada
#
# O resultado e no maximo UMA consulta infrutifera por hora - exatamente o que
# o servico pede - com nota nova aparecendo em ate 20 minutos em vez de duas
# horas. A versao anterior rodava de 2 em 2 h e deixava dinheiro na mesa: nao
# reduzia risco nenhum, so atrasava a chegada.
#
# De madrugada nao roda: nota de fornecedor e emitida em horario comercial, e
# uma varredura as 3h so gastaria a primeira consulta do dia seguinte.
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

# UM gatilho com REPETICAO, e nao catorze gatilhos diarios: o agendador do
# Windows tem repeticao nativa, e uma lista de horarios fixos e o tipo de
# coisa que fica desatualizada quando alguem quer mudar a janela.
#
# Ver o comentario do topo: quem limita a cadencia e o freio do SCRIPT, nao
# este relogio. Passagem barrada pelo freio nem chega a falar com a SEFAZ.
$gatilho = New-ScheduledTaskTrigger -Daily -At 06:00
$gatilho.Repetition = (New-ScheduledTaskTrigger -Once -At 06:00 `
  -RepetitionInterval (New-TimeSpan -Minutes 20) `
  -RepetitionDuration (New-TimeSpan -Hours 14)).Repetition
$gatilhos = @($gatilho)

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# Dez caixas, cada uma com teto de 40 lotes. A PRIMEIRA carga e a longa; as
# seguintes terminam em segundos. 15 min cobre com folga - e o teto tem de ser
# MENOR que o intervalo de repeticao (20 min), senao duas execucoes se
# encontram. `IgnoreNew` ja evita a sobreposicao, mas ai a passagem seguinte
# seria simplesmente perdida.
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
Write-Host "Confira na tela Saude do Servidor: ela deve sair de 'nao registrada'."
Write-Host ""
Write-Host "Filial sem certificado A1 no cofre e PULADA com aviso - ela nao"
Write-Host "derruba a recolha das outras nove."
