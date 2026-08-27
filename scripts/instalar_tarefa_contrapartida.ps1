# Registra a tarefa agendada da emissao do CT-e de contrapartida.
#
# COMO ESTA TAREFA E DIFERENTE DAS OUTRAS
# ---------------------------------------
# As tarefas de telemetria e pneus COLETAM dado. Esta EMITE DOCUMENTO FISCAL em
# nome de outra empresa. Por isso ela nao decide nada sozinha:
#
#   - dispara de 5 em 5 minutos, mas quem diz se e hora e o CORTEX, lendo o
#     intervalo configurado na tela (Administracao > Integracoes). Mudar o
#     intervalo la tem efeito imediato, sem reinstalar tarefa;
#   - se a automacao estiver DESLIGADA, o script sai sem fazer nada. A tarefa
#     existir nao liga a emissao - sao dois interruptores diferentes;
#   - o ambiente (homologacao ou producao) tambem sai da tela, nao daqui.
#
# Ou seja: instalar isto e seguro mesmo com tudo desligado. Ela so passa a
# emitir quando alguem ligar a automacao pela tela, e fica registrado quem foi.
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
$nome = 'Cortex Sulista - CTe Contrapartida'

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
$alvo = Join-Path $repo "scripts\emitir_lote.py"
if (-not (Test-Path $alvo)) { throw "script nao encontrado em $alvo" }

Write-Host "repo: $repo"
Log "acao: $py $alvo --agendado"

# --agendado ja implica desassistido e valendo, e le o ambiente da configuracao.
# Nao passamos --producao aqui de proposito: o ambiente e decisao da TELA, e
# deixa-lo no argumento da tarefa criaria uma segunda fonte da verdade que
# ninguem lembraria de conferir.
$acao = New-ScheduledTaskAction -Execute $py `
  -Argument "`"$alvo`" --agendado" -WorkingDirectory $repo

# DE 5 EM 5 MINUTOS - que e o piso do intervalo configuravel. A tarefa nao
# emite a cada 5 minutos: ela PERGUNTA se esta na hora. Rodar mais rapido que o
# piso so gastaria consulta; mais devagar impediria de honrar um intervalo
# curto configurado na tela.
$inicio = (Get-Date).Date.AddHours(5).AddMinutes(5)
$gatilhos = @(
  (New-ScheduledTaskTrigger -Once -At $inicio),
  (New-ScheduledTaskTrigger -AtStartup)
)
$gatilhos[0].Repetition = (New-ScheduledTaskTrigger -Once -At $inicio `
  -RepetitionInterval (New-TimeSpan -Minutes 5) `
  -RepetitionDuration ([TimeSpan]::MaxValue)).Repetition

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
  -Description ('Emissao do CT-e de contrapartida do agregado. Dispara de 5 em ' +
                '5 min e o CORTEX decide se e hora, pelo intervalo configurado ' +
                'em Administracao > Integracoes. Se a automacao estiver ' +
                'desligada, nao faz nada.') | Out-Null

Log "tarefa registrada: $nome"
Write-Host ""
Write-Host "Tarefa registrada." -ForegroundColor Green
Write-Host "Ela NAO emite nada enquanto a automacao estiver desligada."
Write-Host "Ligue em Administracao > Integracoes > Emissao do CT-e de contrapartida."
Log "----- fim -----"
