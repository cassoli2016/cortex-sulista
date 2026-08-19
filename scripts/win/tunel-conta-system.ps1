# CORTEX -- muda SO A CONTA da tarefa do tunel para SISTEMA. Nada mais.
#
# POR QUE MINIMO: as tentativas anteriores usavam Set-ScheduledTask reaplicando
# Principal + Trigger + Settings de uma vez. Os objetos de trigger devolvidos por
# Get-ScheduledTask nem sempre sao validos de volta, e a chamada falhava com
# 0x80070002 levando a tarefa junto. schtasks /change /ru mexe apenas na conta.
#
# Nao adiciona gatilho de boot: a tarefa ja tem os gatilhos dela, e mexer neles
# foi exatamente o que quebrou.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\win\tunel-conta-system.ps1

$ErrorActionPreference = 'Continue'
$TAREFA = 'Cortex Sulista - Tunnel'
$URL    = 'https://cortex.cassolitech.com.br/'
$repo   = 'C:\Users\inteligencia\Documents\cortex-sulista'
$backup = Join-Path $repo 'data\win\backup-tarefas'

function Passo($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "   OK   $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   !    $t" -ForegroundColor Yellow }

function PainelNoAr([int]$n = 12) {
  foreach ($i in 1..$n) {
    Start-Sleep -Seconds 3
    $r = try { Invoke-WebRequest $URL -UseBasicParsing -TimeoutSec 20 } catch { $null }
    if ($r -and $r.StatusCode -eq 200) { return $true }
    Write-Host ("   tentativa {0}/{1}: ainda nao" -f $i, $n)
  }
  return $false
}

Passo '1. A tarefa existe?'
$t = Get-ScheduledTask -TaskName $TAREFA -ErrorAction SilentlyContinue
if (-not $t) {
  Aviso "'$TAREFA' nao existe -- restaurando do backup"
  $arq = Get-ChildItem $backup -Filter *.xml -ErrorAction SilentlyContinue | Where-Object {
    ([xml](Get-Content $_.FullName -Raw)).Task.RegistrationInfo.URI.TrimStart('\') -eq $TAREFA
  } | Select-Object -First 1
  if (-not $arq) { Aviso "sem backup para '$TAREFA' -- pare aqui e me avise"; exit 1 }
  Register-ScheduledTask -TaskName $TAREFA -Xml (Get-Content $arq.FullName -Raw) `
    -User 'inteligencia' | Out-Null
  $t = Get-ScheduledTask -TaskName $TAREFA -ErrorAction SilentlyContinue
  if (-not $t) { Aviso 'nao consegui restaurar a tarefa'; exit 1 }
  Ok 'tarefa restaurada do backup'
}
Write-Host ("   conta atual: {0} / {1}" -f $t.Principal.UserId, $t.Principal.LogonType)

Passo '2. Trocando apenas a conta para SISTEMA'
# schtasks e a ferramenta classica: /ru SYSTEM nao pede senha e nao toca em
# gatilho, acao nem configuracao
& schtasks.exe /change /tn "$TAREFA" /ru "SYSTEM" 2>&1 | ForEach-Object { Write-Host "      $_" }

$t2 = Get-ScheduledTask -TaskName $TAREFA -ErrorAction SilentlyContinue
if (-not $t2) { Aviso 'a tarefa sumiu apos a alteracao -- me avise antes de tentar de novo'; exit 1 }
Write-Host ("   conta agora: {0} / {1}" -f $t2.Principal.UserId, $t2.Principal.LogonType)
if ($t2.Principal.LogonType -ne 'ServiceAccount') {
  Aviso 'a conta nao mudou para ServiceAccount'
  exit 1
}
Ok 'conta alterada'

Passo '3. Subindo o tunel'
Get-Process cloudflared -ErrorAction SilentlyContinue |
  ForEach-Object { Ok "encerrando cloudflared pid $($_.Id)"; Stop-Process -Id $_.Id -Force }
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $TAREFA

if (PainelNoAr 12) {
  Ok 'painel respondendo 200 com o tunel sob SISTEMA'
  Passo 'Estado final'
  Get-ScheduledTask | Where-Object { $_.TaskName -like '*ortex*' } | ForEach-Object {
    Write-Host ("   '{0}'  {1}/{2}" -f $_.TaskName, $_.Principal.UserId, $_.Principal.LogonType)
  }
  Write-Host ""
  Write-Host "Agora: FACA LOGOFF e abra o painel de outro dispositivo." -ForegroundColor Yellow
} else {
  Aviso 'o painel nao voltou -- devolvendo a conta para inteligencia'
  & schtasks.exe /change /tn "$TAREFA" /ru "inteligencia" 2>&1 | Out-Null
  Start-ScheduledTask -TaskName $TAREFA -ErrorAction SilentlyContinue
  if (PainelNoAr 10) { Ok 'painel de volta no modo antigo' }
  else { Aviso 'painel ainda fora -- rode a tarefa manualmente ou reinicie a maquina' }
  exit 1
}
