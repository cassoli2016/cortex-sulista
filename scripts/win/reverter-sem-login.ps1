# CORTEX -- desfaz o rodar-sem-login.ps1, voltando ao estado anterior.
#
# Restaura as tarefas a partir do XML exportado antes da mudanca, remove o
# servico do cloudflared e reabilita a tarefa do tunel.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\win\reverter-sem-login.ps1

$ErrorActionPreference = 'Continue'
$repo = 'C:\Users\inteligencia\Documents\cortex-sulista'
$backup = Join-Path $repo 'data\win\backup-tarefas'

function Ok($t)    { Write-Host "   OK   $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   !    $t" -ForegroundColor Yellow }

Write-Host "== Revertendo" -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath $backup)) {
  Aviso "sem backup em $backup -- nada a restaurar nas tarefas"
} else {
  Get-ChildItem $backup -Filter *.xml | ForEach-Object {
    $nome = ($_.BaseName -replace '_', ' ')
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
