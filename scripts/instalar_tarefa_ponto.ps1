# Registra a tarefa agendada da COLETA DE BATIDAS no Ponto Certificado.
#
# Por que existe: a batida de ponto nasce no Ponto Certificado (REP-P em
# nuvem). O ERP le o MESMO fornecedor, mas so pelo AFD - formato legal, sem
# coordenada - e por importacao MANUAL: mediana de 3 dias entre execucoes,
# maximo de 18, uma unica pessoa executando. Medido em 09/09/2026, o ERP
# enxergava ate 06/09 enquanto o fornecedor ja tinha a batida das 20h42 do
# proprio dia.
#
# HORARIO: de 10 em 10 minutos, o dia inteiro.
#
# E os 10 minutos NAO sao para "tempo real". A batida chega ao fornecedor em 12
# segundos (mediana medida); a cadencia existe para que uma queda de uma hora
# custe seis execucoes perdidas e nao um dia de apuracao.
#
# O WEBHOOK FICOU DE FORA POR DECISAO de quem opera (11/09/2026). A API expoe
# `WebhookSubscription` e a troca parece um avanco obvio — nao e: dez minutos
# de atraso nao incomodam ninguem aqui, e o push traz porta aberta, segredo de
# assinatura e uma fila que so falha quando ja falhou. O cursor e idempotente e
# se recupera sozinho.
#
# NAO HA FREIO DO FORNECEDOR A RESPEITAR, ao contrario da SEFAZ: nenhuma
# punicao por consulta sem resultado foi observada, e a chamada do cursor
# custa 0,4 s mesmo quando devolve vazio. O que limita a cadencia aqui e o
# bom senso, nao um castigo.
#
# DE MADRUGADA RODA. Ha batida noturna de verdade nesta operacao - a amostra
# de sete dias tem marcacoes a 01:20 e as 04:01 - e uma janela comercial
# deixaria o turno da noite esperando ate a manha.
#
# Segue o mesmo padrao das tarefas ja instaladas (API, AutoDeploy, Tunnel,
# Smartec, Pneus, Backup, Monkey, DFe): conta SISTEMA, para nao depender de
# sessao aberta.
#
# Uso (PowerShell como Administrador). CAMINHO COMPLETO de proposito: o
# PowerShell elevado abre em C:\Windows\system32, onde caminho relativo nao
# resolve.
#   powershell -ExecutionPolicy Bypass -File "C:\Users\inteligencia\Documents\cortex-sulista\scripts\instalar_tarefa_ponto.ps1"

$ErrorActionPreference = 'Stop'

# LOG EM ARQUIVO: a janela elevada e outra janela, e o erro morre com ela.
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
$nome = 'Cortex Sulista - Ponto Certificado'

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
# PATH do usuario, e -WorkingDirectory nao chega ao interpretador.
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "python do venv nao encontrado em $py" }
$alvo = Join-Path $repo "scripts\coletar_ponto.py"
if (-not (Test-Path $alvo)) { throw "script nao encontrado em $alvo" }

Write-Host "repo: $repo"
Write-Host "py:   $py"
Log "acao: $py $alvo"
$acao = New-ScheduledTaskAction -Execute $py `
  -Argument "`"$alvo`"" -WorkingDirectory $repo

# UM gatilho com REPETICAO nativa, nao uma lista de horarios: lista fixa e o
# tipo de coisa que fica desatualizada quando alguem muda a janela.
$gatilho = New-ScheduledTaskTrigger -Daily -At 00:05
$gatilho.Repetition = (New-ScheduledTaskTrigger -Once -At 00:05 `
  -RepetitionInterval (New-TimeSpan -Minutes 10) `
  -RepetitionDuration (New-TimeSpan -Hours 24)).Repetition
$gatilhos = @($gatilho)

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# O TETO TEM DE SER MENOR QUE O INTERVALO (10 min), senao duas execucoes se
# encontram. `IgnoreNew` ja evita a sobreposicao, mas ai a passagem seguinte
# seria simplesmente perdida. A coleta corrente termina em segundos: 8 min e
# folga larga, e so a primeira carga (ja feita) era longa.
$cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 8) `
  -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilhos `
  -Principal $principal -Settings $cfg -Force | Out-Null

$t = Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue
if (-not $t) { throw "A tarefa NAO foi criada. Nada foi registrado." }
Log "tarefa '$nome' registrada com sucesso"

# RODA UMA VEZ AGORA para PROVAR a tarefa: caminho errado no -Execute registra
# com sucesso e falha 0x80070002 toda vez - sem rodar aqui, isso so apareceria
# no primeiro horario, longe de quem instalou.
Log "disparando a primeira execucao"
Start-ScheduledTask -TaskName $nome
Start-Sleep -Seconds 12
$i = Get-ScheduledTask -TaskName $nome | Get-ScheduledTaskInfo
Log ("primeira execucao: ultima=" + $i.LastRunTime + " resultado=" + $i.LastTaskResult)
if ($i.LastTaskResult -ne 0 -and $i.LastTaskResult -ne 267009) {
  Write-Host ""
  Write-Host ("ATENCAO: a primeira execucao terminou com codigo " + $i.LastTaskResult) -ForegroundColor Yellow
  Write-Host "         0x80070002 = caminho nao encontrado; confira o -Execute."
}
Write-Host ""
Write-Host "OK: tarefa '$nome' registrada." -ForegroundColor Green
$t | Select-Object TaskName, State, @{n='Conta';e={$_.Principal.UserId}} | Format-Table -AutoSize
Write-Host ""
Write-Host "A coleta usa a credencial EMPRESTADA do ERP ate que a propria seja"
Write-Host "cadastrada em Integracoes > Ponto Certificado. O cartao da Saude do"
Write-Host "Servidor diz qual esta em uso."
