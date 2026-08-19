# CORTEX -- tunel rodando SEM LOGIN pela tarefa agendada, como SISTEMA.
#
# POR QUE ASSIM: o servico nativo do cloudflared instalou mas nunca iniciou
# nesta maquina (26 reinicios em loop, sempre morrendo em segundos). Ja a tarefa
# como SISTEMA funcionou de primeira na API e no AutoDeploy hoje. Este script
# aplica ao tunel o que comprovadamente funciona aqui.
#
# Remove o servico quebrado (que fica em laco de reinicio consumindo recurso),
# converte a tarefa do tunel para SISTEMA e valida com requisicao real ao painel.
# Se o painel nao voltar, DESFAZ sozinho.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\win\tunel-como-tarefa-system.ps1

$ErrorActionPreference = 'Continue'
$TAREFA = 'Cortex Sulista - Tunnel'
$URL    = 'https://cortex.cassolitech.com.br/'

function Passo($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "   OK   $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   !    $t" -ForegroundColor Yellow }

function EhLocalSystem([string]$conta) {
  if ([string]::IsNullOrWhiteSpace($conta)) { return $false }
  try {
    $sid = (New-Object System.Security.Principal.NTAccount($conta)
           ).Translate([System.Security.Principal.SecurityIdentifier]).Value
    if ($sid -eq 'S-1-5-18') { return $true }
  } catch { }
  return @('SYSTEM', 'SISTEMA', 'S-1-5-18') -contains $conta.Trim().ToUpper()
}

function PainelNoAr([int]$n = 12) {
  foreach ($i in 1..$n) {
    Start-Sleep -Seconds 3
    $r = try { Invoke-WebRequest $URL -UseBasicParsing -TimeoutSec 20 } catch { $null }
    if ($r -and $r.StatusCode -eq 200) { return $true }
    Write-Host ("   tentativa {0}/{1}: ainda nao" -f $i, $n)
  }
  return $false
}

Passo '1. Removendo o servico que nunca iniciou'
$svc = Get-Service | Where-Object { $_.Name -like '*loudflare*' } | Select-Object -First 1
if ($svc) {
  # desliga o inicio automatico ANTES de parar: senao o Windows o reinicia
  # sozinho pela acao de recuperacao e o laco continua
  Set-Service $svc.Name -StartupType Disabled -ErrorAction SilentlyContinue
  Stop-Service $svc.Name -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
  & sc.exe delete $svc.Name | Out-Null
  Ok "servico $($svc.Name) desabilitado e removido"
} else { Ok 'nenhum servico cloudflared para remover' }
Get-Process cloudflared -ErrorAction SilentlyContinue |
  ForEach-Object { Ok "encerrando cloudflared pid $($_.Id)"; Stop-Process -Id $_.Id -Force }

Passo '2. Convertendo a tarefa do tunel para SISTEMA'
$tarefa = Get-ScheduledTask -TaskName $TAREFA -ErrorAction SilentlyContinue
if (-not $tarefa) { Aviso "tarefa '$TAREFA' nao encontrada"; exit 1 }
$antes = $tarefa.Principal.LogonType

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' `
               -LogonType ServiceAccount -RunLevel Highest
$gatilhos = @($tarefa.Triggers)
if (-not ($gatilhos | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskBootTrigger' })) {
  $gatilhos += New-ScheduledTaskTrigger -AtStartup
}
$config = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -StartWhenAvailable `
            -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
            -MultipleInstances IgnoreNew
$config.ExecutionTimeLimit = 'PT0S'   # o tunel fica de pe: sem limite de duracao

Enable-ScheduledTask -TaskName $TAREFA -ErrorAction SilentlyContinue | Out-Null
Set-ScheduledTask -TaskName $TAREFA -Principal $principal -Trigger $gatilhos `
  -Settings $config | Out-Null

$p = (Get-ScheduledTask -TaskName $TAREFA).Principal
if ($p.LogonType -ne 'ServiceAccount' -or -not (EhLocalSystem $p.UserId)) {
  Aviso "a tarefa nao aceitou a mudanca (ficou $($p.UserId)/$($p.LogonType))"
  exit 1
}
Ok "$TAREFA : $antes -> $($p.UserId) / ServiceAccount, com gatilho de boot"

Passo '3. Subindo o tunel pela tarefa'
Start-ScheduledTask -TaskName $TAREFA
if (PainelNoAr 12) {
  Ok 'painel publico respondendo 200 pelo tunel sob SISTEMA'
} else {
  Aviso 'o painel nao voltou -- devolvendo a tarefa para a conta interativa'
  $volta = New-ScheduledTaskPrincipal -UserId 'inteligencia' -LogonType Interactive -RunLevel Limited
  Set-ScheduledTask -TaskName $TAREFA -Principal $volta | Out-Null
  Start-ScheduledTask -TaskName $TAREFA
  if (PainelNoAr 10) { Ok 'painel de volta no modo antigo' }
  else { Aviso 'painel AINDA fora -- reinicie a maquina para limpar o estado' }
  exit 1
}

Passo '4. Estado final das tres'
foreach ($t in @('Cortex Sulista - API', 'Cortex Sulista - AutoDeploy', $TAREFA)) {
  $pp = (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue).Principal
  if ($pp) { Write-Host ("   {0,-32} {1} / {2}" -f $t, $pp.UserId, $pp.LogonType) }
}
Write-Host ""
Write-Host "Se as tres estao como SISTEMA / ServiceAccount, o teste final e:" -ForegroundColor Yellow
Write-Host "FACA LOGOFF e abra o painel de outro dispositivo." -ForegroundColor Yellow
