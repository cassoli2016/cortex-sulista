# Registra a tarefa agendada da CAIXA DE XML - o e-mail xml@sulista.com.br,
# por onde chega o XML das notas em que a Sulista NAO e parte.
#
# Por que existe: a caixa da SEFAZ so entrega documento em que o CNPJ e PARTE
# (destinatario, transportador, emitente ou tomador). A nota do cliente que a
# Sulista vai transportar, mandada antes de o frete existir, nunca vai chegar
# por la - e chega por e-mail.
#
# HORARIO: de 30 em 30 minutos, o DIA INTEIRO.
#
# E aqui NAO existe o freio que a outra porta tem. A SEFAZ pune consulta sem
# resultado (cStat 656, uma hora de castigo) e por isso a tarefa dela tem a
# cadencia calculada; o Microsoft Graph nao pune leitura, e uma listagem que
# nao acha nada custa uma requisicao. O que decide os 30 minutos e o outro
# lado: alguem mandou o XML e precisa dele na operacao, e meia hora e o tempo
# em que a pessoa ainda nao ligou perguntando se chegou.
#
# DE MADRUGADA RODA, ao contrario da tarefa da SEFAZ: sistema de cliente manda
# XML em lote as 2h da manha, e nao ha cota para economizar.
#
# Segue o mesmo padrao das tarefas ja instaladas (API, AutoDeploy, Tunnel,
# Smartec, Pneus, Backup, Monkey, DFe SEFAZ): conta SISTEMA, para nao depender
# de sessao aberta.
#
# Uso (PowerShell como Administrador). CAMINHO COMPLETO de proposito: o
# PowerShell elevado abre em C:\Windows\system32, onde o caminho relativo nao
# resolve ("O argumento ... nao existe").
#   powershell -ExecutionPolicy Bypass -File "C:\Users\inteligencia\Documents\cortex-sulista\scripts\instalar_tarefa_xml_email.ps1"


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
$nome = 'Cortex Sulista - Caixa de XML'

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
$alvo = Join-Path $repo "scripts\coletar_xml_email.py"
if (-not (Test-Path $alvo)) { throw "script nao encontrado em $alvo" }

Write-Host "repo: $repo"
Write-Host "py:   $py"
Log "acao: $py $alvo"
$acao = New-ScheduledTaskAction -Execute $py `
  -Argument "`"$alvo`"" -WorkingDirectory $repo

# UM gatilho com REPETICAO de 24 horas: a caixa recebe a qualquer hora, e nao
# ha cota a economizar de madrugada.
$gatilho = New-ScheduledTaskTrigger -Daily -At 00:05
$gatilho.Repetition = (New-ScheduledTaskTrigger -Once -At 00:05 `
  -RepetitionInterval (New-TimeSpan -Minutes 30) `
  -RepetitionDuration (New-TimeSpan -Hours 24)).Repetition
$gatilhos = @($gatilho)

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# 10 min de teto: a janela padrao e de 30 dias de caixa, e mesmo uma primeira
# carga com centenas de mensagens termina bem antes. O teto tem de ser MENOR
# que o intervalo de repeticao (30 min), senao duas execucoes se encontram --
# `IgnoreNew` ja evita a sobreposicao, mas ai a passagem seguinte seria
# simplesmente perdida.
$cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
  -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilhos `
  -Principal $principal -Settings $cfg -Force | Out-Null

$t = Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue
if (-not $t) { throw "A tarefa NAO foi criada. Nada foi registrado." }
Log "tarefa '$nome' registrada com sucesso"

# RODA UMA VEZ AGORA, para PROVAR a tarefa na hora: caminho errado no -Execute
# registra com sucesso e falha 0x80070002 toda vez -- sem rodar aqui, isso so
# apareceria no primeiro horario, longe de quem instalou.
Log "disparando a primeira execucao"
Start-ScheduledTask -TaskName $nome
Start-Sleep -Seconds 8
$i = Get-ScheduledTask -TaskName $nome | Get-ScheduledTaskInfo
Log ("primeira execucao: ultima=" + $i.LastRunTime + " resultado=" + $i.LastTaskResult)
if ($i.LastTaskResult -ne 0 -and $i.LastTaskResult -ne 267009) {
  # 267009 = ainda rodando. Qualquer outro codigo diferente de 0 e falha, e ela
  # tem de aparecer AQUI e nao amanha.
  Write-Host ""
  Write-Host ("ATENCAO: a primeira execucao terminou com codigo " + $i.LastTaskResult) -ForegroundColor Yellow
  Write-Host "         0x80070002 = caminho nao encontrado; confira o -Execute."
}
Write-Host ""
Write-Host "OK: tarefa '$nome' registrada." -ForegroundColor Green
$t | Select-Object TaskName, State, @{n='Conta';e={$_.Principal.UserId}} | Format-Table -AutoSize
Write-Host ""
Write-Host "SEM CREDENCIAL A TAREFA NAO FALHA: ela diz 'nao configurada' e sai"
Write-Host "com sucesso. Instalacao incompleta nao e erro, e uma tarefa que"
Write-Host "acusa falha a cada meia hora ensina a ignorar o alarme."
Write-Host ""
Write-Host "Configure em Administracao > Integracoes > Caixa de XML:"
Write-Host "  - ID do tenant e do aplicativo (Entra ID)"
Write-Host "  - segredo do aplicativo"
Write-Host "  - endereco da caixa (xml@sulista.com.br)"
