# CORTEX -- desfaz o rodar-sem-login.ps1, voltando ao estado anterior.
#
# Restaura as tarefas a partir do XML exportado antes da mudanca, remove o
# servico do cloudflared e reabilita a tarefa do tunel.
#
# GRANULAR de proposito: reverter tudo por causa de um problema so do tunel
# desfez API e AutoDeploy que estavam funcionando como SISTEMA. Agora:
#   -Tudo     reverte as 3 (comportamento antigo)
#   -Tunel    reverte SO o tunel, preservando API e AutoDeploy convertidos
# Sem parametro, assume -Tunel, que e o caso comum.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\win\reverter-sem-login.ps1 -Tunel
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\win\reverter-sem-login.ps1 -Tudo

[CmdletBinding()]
param([switch]$Tudo, [switch]$Tunel)

$ErrorActionPreference = 'Continue'
if (-not $Tudo -and -not $Tunel) { $Tunel = $true }
$repo = 'C:\Users\inteligencia\Documents\cortex-sulista'
$backup = Join-Path $repo 'data\win\backup-tarefas'

function Ok($t)    { Write-Host "   OK   $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   !    $t" -ForegroundColor Yellow }

Write-Host ("== Revertendo ({0})" -f $(if ($Tudo) { 'TUDO' } else { 'so o tunel' })) -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath $backup)) {
  Aviso "sem backup em $backup -- nada a restaurar nas tarefas"
} elseif (-not $Tudo) {
  Aviso 'API e AutoDeploy preservados como estao (use -Tudo para reverter tambem)'
} else {
  Get-ChildItem $backup -Filter *.xml | ForEach-Object {
    # BUG QUE ISTO CORRIGE: o nome do arquivo troca CADA caractere invalido por
    # '_', entao "Cortex Sulista - API" vira "Cortex_Sulista___API". Desfazer com
    # -replace '_',' ' devolvia "Cortex Sulista   API" -- TRES espacos, nome
    # diferente do original. O reverter registrava tarefas novas com nome
    # corrompido e deixava as originais para tras.
    # O nome verdadeiro esta DENTRO do XML (URI), nao no nome do arquivo.
    $xmlDoc = [xml](Get-Content $_.FullName -Raw)
    $uri = $xmlDoc.Task.RegistrationInfo.URI
    $nome = if ($uri) { $uri.TrimStart('\') } else { ($_.BaseName -replace '_+', ' ') }
    try {
      $xml = Get-Content $_.FullName -Raw
      Unregister-ScheduledTask -TaskName $nome -Confirm:$false -ErrorAction SilentlyContinue
      Register-ScheduledTask -TaskName $nome -Xml $xml -User 'inteligencia' | Out-Null
      Ok "restaurada: $nome"
    } catch {
      Aviso "falhou ao restaurar $nome : $($_.Exception.Message)"
      Aviso "  (a tarefa pedia senha? entao restaure pelo Agendador de Tarefas, importando $($_.FullName))"
    }
  }
}

$svc = Get-Service | Where-Object { $_.Name -like '*cloudflare*' } | Select-Object -First 1
if ($svc) {
  Stop-Service $svc.Name -Force -ErrorAction SilentlyContinue
  $cf = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
  # o cloudflared loga em stderr tambem no uninstall: nao deixar isso abortar
  $pref = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try { if (Test-Path -LiteralPath $cf) { & $cf service uninstall 2>&1 | Out-Null } }
  finally { $ErrorActionPreference = $pref }
  Ok "servico $($svc.Name) removido"
}
Enable-ScheduledTask -TaskName 'Cortex Sulista - Tunnel' -ErrorAction SilentlyContinue | Out-Null
Start-ScheduledTask -TaskName 'Cortex Sulista - Tunnel' -ErrorAction SilentlyContinue
Ok "tarefa do tunel reabilitada"
Write-Host ""
Aviso 'Confira o painel e, se preciso, reinicie a maquina para voltar ao estado limpo.'
