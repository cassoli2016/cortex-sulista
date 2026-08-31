# Registra a tarefa agendada da coleta da Smartec.
#
# Por que existe: o aviso de prazo de indicacao de condutor le o BANCO, nao a
# Smartec. Isso e de proposito - a tela abre em milissegundos e nao cai junto
# se o fornecedor estiver fora -, mas cria uma dependencia que so se enxerga
# quando quebra: SEM COLETA, o banco envelhece e o aviso silencia. E silencio,
# ali, e indistinguivel de "esta tudo indicado".
#
# O provedor do WhatsApp recusa dado velho (HORAS_FRESCOR em
# api/smartec/leitura.py), entao a falha aparece como recusa dita em vez de
# silencio. Mas quem impede a recusa e esta tarefa rodar.
#
# A varredura leva ~20 s e faz ~265 chamadas, todas de LEITURA e todas contra
# o banco da Smartec - nao contra o DETRAN. Nao ha custo por consulta a orgao.
#
# HORARIO: 06:20 e 14:20, ANTES dos horarios em que o aviso costuma sair. A
# ordem importa: coletar depois de avisar seria avisar com o dado de ontem.
#
# Segue o mesmo padrao das tarefas ja instaladas (API, AutoDeploy, Tunnel,
# Telemetria, Pneus, Backup): conta SISTEMA, para nao depender de sessao
# aberta.
#
# Uso (PowerShell como Administrador). CAMINHO COMPLETO de proposito: o
# PowerShell elevado abre em C:\Windows\system32, onde o caminho relativo nao
# resolve ("O argumento ... nao existe").
#   powershell -ExecutionPolicy Bypass -File "C:\Users\inteligencia\Documents\cortex-sulista\scripts\instalar_tarefa_smartec.ps1"


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
$nome = 'Cortex Sulista - Smartec'

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
$alvo = Join-Path $repo "scripts\coletar_smartec.py"
if (-not (Test-Path $alvo)) { throw "script nao encontrado em $alvo" }

Write-Host "repo: $repo"
Write-Host "py:   $py"
Log "acao: $py $alvo"
$acao = New-ScheduledTaskAction -Execute $py `
  -Argument "`"$alvo`"" -WorkingDirectory $repo

# DUAS VEZES AO DIA, e nao de hora em hora. Tres razoes:
#
# 1. O NUMERO QUE DECIDE MUDA DE DIA, NAO DE HORA. O aviso e sobre "quantos
#    dias faltam para o prazo de indicacao", e isso so vira a meia-noite.
#    Coletar de hora em hora produziria o mesmo numero vinte e quatro vezes.
# 2. Sao ~265 chamadas por passagem. De hora em hora seriam ~6.400 por dia
#    contra ~530 - vinte vezes o trafego para o mesmo resultado.
# 3. A propria Smartec pesquisa os orgaos em lote e carimba DATA_PESQUISA. O
#    dado dela nao muda continuamente; buscar mais vezes nao o torna mais novo.
#
# A segunda passagem existe como RETENTATIVA: se a da manha falhar por rede,
# sem ela nada tentaria de novo ate o dia seguinte - e o buraco de um dia so
# aparece quando alguem olha.
$gatilhos = @(
  (New-ScheduledTaskTrigger -Daily -At 06:20),
  (New-ScheduledTaskTrigger -Daily -At 14:20)
)

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# A coleta dos quatro recursos leva ~15 s numa janela de 7 dias. 20 min de
# teto cobre folgado, inclusive uma espera de limite de taxa, e evita tarefa
# pendurada segurando a proxima execucao.
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
Write-Host "Rodando a primeira coleta agora para validar..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $nome
Start-Sleep -Seconds 8
(Get-ScheduledTask -TaskName $nome | Get-ScheduledTaskInfo |
  Select-Object LastRunTime, LastTaskResult, NextRunTime | Format-List)
Write-Host "A trilha de cada passagem fica em jor_carga - inclusive a que"
Write-Host "falhou e a que nao trouxe nada. E dela que a Saude tira o alarme."
