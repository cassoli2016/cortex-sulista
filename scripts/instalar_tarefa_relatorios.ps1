# Registra a tarefa agendada dos RELATORIOS POR E-MAIL.
#
# COMO ELA FUNCIONA
# -----------------
# A tarefa NAO decide nada. Dispara de 15 em 15 minutos e pergunta ao CORTEX
# se ja passou a hora de cada agendamento:
#
#   - horario, destinatarios e frequencia saem da tela (Gestao > E-mail).
#     Mudar la vale na hora, sem reinstalar tarefa;
#   - agendamento DESLIGADO nao envia nada. A tarefa existir nao liga envio
#     nenhum - sao dois interruptores diferentes;
#   - 15 minutos e o passo porque relatorio tem hora marcada, nao urgencia de
#     minuto. Passo menor so gastaria consulta.
#
# Instalar isto e seguro mesmo sem nenhum agendamento cadastrado.
#
# Uso (PowerShell). CAMINHO COMPLETO de proposito: o PowerShell elevado abre em
# C:\Windows\system32, onde o caminho relativo nao resolve.
#   powershell -ExecutionPolicy Bypass -File "C:\Users\inteligencia\Documents\cortex-sulista\scripts\instalar_tarefa_contrapartida.ps1"

$ErrorActionPreference = 'Stop'

# LOG EM ARQUIVO. A janela elevada e outra janela: se o script falha nela, o
# erro morre junto quando ela fecha, e do lado de ca so se ve "nao registrou".
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
$nome = 'Cortex Sulista - Relatorios por e-mail'

# AUTO-ELEVACAO: registrar um principal SISTEMA exige elevacao, sem alternativa.
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
# PATH do usuario; e o -WorkingDirectory nao chega ao interpretador, entao
# caminho relativo falharia com 0x80070002.
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "python do venv nao encontrado em $py" }
$alvo = Join-Path $repo "scripts\enviar_agendados.py"
if (-not (Test-Path $alvo)) { throw "script nao encontrado em $alvo" }

Write-Host "repo: $repo"
Log "acao: $py $alvo"

# Sem argumento nenhum de proposito: tudo que decide o envio - o que, para
# quem, quando - mora na tela. Um parametro aqui criaria uma segunda fonte da
# verdade que ninguem lembraria de conferir.
$acao = New-ScheduledTaskAction -Execute $py `
  -Argument "`"$alvo`"" -WorkingDirectory $repo

# DE 15 EM 15 MINUTOS. A tarefa nao envia a cada 15 minutos: ela PERGUNTA se
# esta na hora de algum agendamento. Relatorio tem hora marcada e nao urgencia
# de minuto, entao passo menor so gastaria consulta - e passo maior faria o
# relatorio das 07:00 sair as 07:29 com frequencia.
#
# GATILHO DIARIO, e nao "uma vez, repetindo para sempre": o
# [TimeSpan]::MaxValue que a documentacao ensina para "indefinidamente" vira
# P99999999DT23H59M59S no XML, que o Agendador do Windows RECUSA - "valor
# formatado incorretamente ou fora do intervalo". Nao ha aviso: a tarefa
# simplesmente nao e criada. Diario + 23h55 de repeticao cobre o dia inteiro e
# e o mesmo padrao das tarefas de telemetria e pneus, que ja rodam ha meses.
$gatilhos = @(
  (New-ScheduledTaskTrigger -Daily -At 00:01),
  (New-ScheduledTaskTrigger -AtStartup)
)
$gatilhos[0].Repetition = (New-ScheduledTaskTrigger -Once -At 00:01 `
  -RepetitionInterval (New-TimeSpan -Minutes 15) `
  -RepetitionDuration (New-TimeSpan -Hours 23 -Minutes 55)).Repetition

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount `
  -RunLevel Highest

# StartWhenAvailable: se a maquina estava desligada na hora, roda ao voltar.
# ExecutionTimeLimit de 30 min: um lote travado nao pode ficar preso para
# sempre segurando a proxima execucao.
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

if (Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue) {
  Log "tarefa ja existe - substituindo"
  Unregister-ScheduledTask -TaskName $nome -Confirm:$false
}
Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilhos `
  -Principal $principal -Settings $config `
  -Description ('Relatorios do CORTEX enviados por e-mail. Dispara de 15 em ' +
                '15 min e o CORTEX decide se e hora, pelos agendamentos ' +
                'configurados em Gestao > E-mail. Sem agendamento ligado, ' +
                'nao faz nada.') | Out-Null

Log "tarefa registrada: $nome"
Write-Host ""
Write-Host "Tarefa registrada." -ForegroundColor Green
Write-Host "Ela NAO envia nada enquanto nao houver agendamento LIGADO."
Write-Host "Cadastre em Gestao > E-mail > Relatorios agendados."
Log "----- fim -----"
