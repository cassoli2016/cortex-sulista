# CORTEX -- faz as 3 tarefas rodarem SEM LOGIN (caminho A: nativo, sem download).
#
# O QUE MUDA: hoje as tarefas rodam como 'inteligencia' com LogonType
# Interactive, o que as mata quando ninguem esta logado. Passam a rodar como
# SYSTEM (LogonType ServiceAccount), com gatilho na inicializacao e reinicio
# automatico em falha. Nenhuma senha e pedida ou armazenada.
#
# O cloudflared vira SERVICO NATIVO -- ele tem suporte proprio, e servico de
# verdade e melhor que tarefa para um processo que precisa ficar de pe.
#
# SEGURANCA DA OPERACAO: exporta a configuracao atual de cada tarefa antes de
# mexer (data\win\backup-tarefas\), valida cada etapa e PARA no primeiro erro,
# sem desfazer o que ja funcionava. Reverter: scripts\win\reverter-sem-login.ps1
#
# Rodar como Administrador:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\win\rodar-sem-login.ps1
#
# Para so ver o que seria feito, sem mexer em nada:
#   ... -File scripts\win\rodar-sem-login.ps1 -Simular

[CmdletBinding()]
param([switch]$Simular)

$ErrorActionPreference = 'Stop'
$repo = 'C:\Users\inteligencia\Documents\cortex-sulista'
$backup = Join-Path $repo 'data\win\backup-tarefas'
$TAREFAS = @('Cortex Sulista - API', 'Cortex Sulista - AutoDeploy', 'Cortex Sulista - Tunnel')

function Passo($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "   OK   $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   !    $t" -ForegroundColor Yellow }
function Parar($t) { Write-Host "   XX   $t" -ForegroundColor Red; throw $t }

# --------------------------------------------------------------- pre-requisitos
Passo 'Verificando pre-requisitos'
$souAdmin = ([Security.Principal.WindowsPrincipal] `
  [Security.Principal.WindowsIdentity]::GetCurrent()
  ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $souAdmin) { Parar 'rode este script como Administrador' }
Ok 'sessao com privilegio de administrador'

if (-not (Test-Path -LiteralPath (Join-Path $repo 'api\main.py'))) {
  Parar "o Cortex nao esta em $repo"
}
Ok "repositorio em $repo"

foreach ($t in $TAREFAS) {
  if (-not (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue)) {
    Parar "tarefa nao encontrada: $t"
  }
}
Ok "as 3 tarefas existem"

if ($Simular) { Aviso 'MODO SIMULACAO: nada sera alterado' }

# --------------------------------------------------------------- backup
Passo 'Guardando a configuracao atual das tarefas'
if (-not $Simular) {
  New-Item -ItemType Directory -Path $backup -Force | Out-Null
  foreach ($t in $TAREFAS) {
    $arq = Join-Path $backup ((($t -replace '[^A-Za-z0-9]', '_')) + '.xml')
    Export-ScheduledTask -TaskName $t | Set-Content -Path $arq -Encoding utf8
    Ok "exportada: $arq"
  }
} else { Ok "exportaria para $backup" }

# --------------------------------------------------------------- API e AutoDeploy
# O cloudflared NAO entra aqui: vira servico nativo mais abaixo.
Passo 'Passando API e AutoDeploy para SYSTEM, com inicio no boot'
foreach ($t in @('Cortex Sulista - API', 'Cortex Sulista - AutoDeploy')) {
  $tarefa = Get-ScheduledTask -TaskName $t
  $antes = $tarefa.Principal.LogonType
  if ($Simular) { Aviso "$t : $antes -> ServiceAccount (simulado)"; continue }

  # SYSTEM com LogonType ServiceAccount roda sem login e SEM senha armazenada.
  # RunLevel Highest porque o AutoDeploy reinicia a tarefa da API.
  $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' `
                 -LogonType ServiceAccount -RunLevel Highest

  # mantem os gatilhos que ja existem e ACRESCENTA o de inicializacao, para
  # subir sozinho depois de um reboot
  $gatilhos = @($tarefa.Triggers)
  if (-not ($gatilhos | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskBootTrigger' })) {
    $gatilhos += New-ScheduledTaskTrigger -AtStartup
  }

  $config = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
              -DontStopIfGoingOnBatteries -StartWhenAvailable `
              -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
              -MultipleInstances IgnoreNew
  # sem limite de duracao: a API e um processo que fica de pe
  $config.ExecutionTimeLimit = 'PT0S'

  Set-ScheduledTask -TaskName $t -Principal $principal -Trigger $gatilhos `
    -Settings $config | Out-Null
  $depois = (Get-ScheduledTask -TaskName $t).Principal
  if ($depois.LogonType -ne 'ServiceAccount' -or $depois.UserId -notmatch 'SYSTEM') {
    Parar "$t nao aceitou a mudanca (ficou $($depois.UserId)/$($depois.LogonType))"
  }
  Ok "$t : $antes -> ServiceAccount como SYSTEM, com gatilho de boot"
}

# --------------------------------------------------------------- reinicia a API
Passo 'Reiniciando a API sob a identidade nova'
if (-not $Simular) {
  # mata os uvicorn atuais -- o diagnostico achou DOIS rodando, sobra de restart
  # anterior: um escutava a 8010 e o outro so consumia memoria
  Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine -like '*uvicorn api.main:app*'
  } | ForEach-Object { Ok "encerrando uvicorn pid $($_.Id)"; Stop-Process -Id $_.Id -Force }

  Stop-ScheduledTask -TaskName 'Cortex Sulista - API' -ErrorAction SilentlyContinue
  Start-ScheduledTask -TaskName 'Cortex Sulista - API'

  $subiu = $false
  foreach ($i in 1..20) {
    Start-Sleep -Seconds 2
    if (Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue) {
      $subiu = $true; break
    }
  }
  if (-not $subiu) {
    Parar ('a API nao voltou a escutar na 8010 em 40s. ' +
           'REVERTA com scripts\win\reverter-sem-login.ps1 antes de continuar')
  }
  $pid8010 = (Get-NetTCPConnection -LocalPort 8010 -State Listen)[0].OwningProcess
  $dono = (Get-CimInstance Win32_Process -Filter "ProcessId=$pid8010" |
           Invoke-CimMethod -MethodName GetOwner)
  Ok "8010 respondendo (pid $pid8010, usuario $($dono.Domain)\$($dono.User))"

  $r = try { Invoke-WebRequest 'http://127.0.0.1:8010/' -UseBasicParsing -TimeoutSec 15 } catch { $null }
  if ($r -and $r.StatusCode -eq 200) { Ok "painel responde HTTP 200 localmente" }
  else { Aviso 'a porta abriu mas o HTTP local nao respondeu 200 -- verifique logs' }
} else { Aviso 'reiniciaria a API e validaria a porta 8010 (simulado)' }

# --------------------------------------------------------------- cloudflared
Passo 'Cloudflared como servico nativo'
$cfg = 'C:\Users\inteligencia\.cloudflared'
$sysCfg = 'C:\Windows\System32\config\systemprofile\.cloudflared'
$cf = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
if (-not (Test-Path -LiteralPath $cf)) { Parar "cloudflared nao encontrado em $cf" }

if ($Simular) {
  Aviso "copiaria $cfg -> $sysCfg e rodaria: cloudflared service install"
} else {
  # o servico roda como LocalSystem e le a config do perfil DELE, nao do usuario
  New-Item -ItemType Directory -Path $sysCfg -Force | Out-Null
  Copy-Item (Join-Path $cfg '*') $sysCfg -Force
  Ok "config e credencial copiadas para o perfil do sistema"

  # a tarefa tem de parar ANTES: dois processos no mesmo tunel disputam a conexao
  Stop-ScheduledTask -TaskName 'Cortex Sulista - Tunnel' -ErrorAction SilentlyContinue
  Get-Process cloudflared -ErrorAction SilentlyContinue |
    ForEach-Object { Ok "encerrando cloudflared pid $($_.Id)"; Stop-Process -Id $_.Id -Force }
  Start-Sleep -Seconds 3

  & $cf --config (Join-Path $sysCfg 'config-cortex.yml') service install 2>&1 |
    ForEach-Object { Write-Host "        $_" }
  Start-Sleep -Seconds 3
  $svc = Get-Service -Name 'cloudflared' -ErrorAction SilentlyContinue
  if (-not $svc) { Parar 'o servico cloudflared nao foi criado' }
  if ($svc.Status -ne 'Running') { Start-Service cloudflared; Start-Sleep -Seconds 3 }
  $svc = Get-Service -Name 'cloudflared'
  if ($svc.Status -ne 'Running') { Parar 'servico cloudflared criado mas nao esta rodando' }
  Set-Service -Name 'cloudflared' -StartupType Automatic
  Ok "servico cloudflared rodando e em inicio automatico"

  # so desabilita a tarefa DEPOIS que o servico provou funcionar
  Disable-ScheduledTask -TaskName 'Cortex Sulista - Tunnel' | Out-Null
  Ok "tarefa 'Cortex Sulista - Tunnel' desabilitada (nao excluida)"
}

# --------------------------------------------------------------- validacao final
Passo 'Validacao final'
if (-not $Simular) {
  foreach ($t in @('Cortex Sulista - API', 'Cortex Sulista - AutoDeploy')) {
    $p = (Get-ScheduledTask -TaskName $t).Principal
    Write-Host ("   {0,-32} {1} / {2}" -f $t, $p.UserId, $p.LogonType)
  }
  $cfs = Get-Service cloudflared -ErrorAction SilentlyContinue
  Write-Host ("   {0,-32} {1} / {2}" -f 'cloudflared (servico)', $cfs.Status, $cfs.StartType)
  Write-Host ""
  Write-Host "Agora TESTE DE VERDADE: faca logoff e, de outra maquina, abra" -ForegroundColor Yellow
  Write-Host "https://cortex.cassolitech.com.br -- se abrir, esta resolvido." -ForegroundColor Yellow
  Write-Host "Se algo falhar: powershell -File scripts\win\reverter-sem-login.ps1" -ForegroundColor Yellow
} else {
  Write-Host ""
  Write-Host "Simulacao concluida. Nada foi alterado." -ForegroundColor Yellow
}
