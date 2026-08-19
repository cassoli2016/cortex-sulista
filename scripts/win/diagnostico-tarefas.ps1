# CÓRTEX — diagnóstico das tarefas agendadas, para planejar a virada a serviço.
#
# NÃO altera nada: só lê e imprime. Rode como Administrador:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\win\diagnostico-tarefas.ps1
#
# NENHUMA SENHA é lida, pedida ou impressa por este script.

$ErrorActionPreference = 'Continue'

function Titulo($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }

Titulo "Onde o CORTEX esta instalado"
foreach ($c in @('E:\Cortex-Sulista\cortex-sulista',
                 'C:\Users\inteligencia\Documents\cortex-sulista',
                 'C:\Users\casso\Documents\cortex-sulista')) {
  $marca = if (Test-Path (Join-Path $c 'api\main.py')) { 'EXISTE' } else { 'nao existe' }
  $dep = Join-Path $c 'logs\deployed.txt'
  $commit = if (Test-Path $dep) { (Get-Content $dep -Raw).Trim().Substring(0,[Math]::Min(12,(Get-Content $dep -Raw).Trim().Length)) } else { '-' }
  Write-Host ("  {0,-45} {1,-12} deployed={2}" -f $c, $marca, $commit)
}

Titulo "Tarefas do CORTEX"
Get-ScheduledTask | Where-Object { $_.TaskName -like '*Cortex*' } | ForEach-Object {
  $info = $_ | Get-ScheduledTaskInfo
  $p = $_.Principal
  Write-Host ("  {0}" -f $_.TaskName)
  Write-Host ("      estado          : {0}" -f $_.State)
  Write-Host ("      executa como    : {0}" -f $p.UserId)
  Write-Host ("      LogonType       : {0}   <- 'Interactive' significa que CAI ao deslogar" -f $p.LogonType)
  Write-Host ("      RunLevel        : {0}" -f $p.RunLevel)
  Write-Host ("      ultima execucao : {0}  (resultado {1})" -f $info.LastRunTime, $info.LastTaskResult)
  foreach ($a in $_.Actions) {
    Write-Host ("      acao            : {0} {1}" -f $a.Execute, $a.Arguments)
  }
}

Titulo "Processos em execucao agora"
foreach ($n in @('python','cloudflared','ssh')) {
  $ps = Get-Process -Name $n -ErrorAction SilentlyContinue
  if ($ps) {
    foreach ($proc in $ps) {
      $dono = (Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)" |
               Invoke-CimMethod -MethodName GetOwner -ErrorAction SilentlyContinue)
      Write-Host ("  {0,-12} pid={1,-8} usuario={2}" -f $n, $proc.Id, $(if($dono){"$($dono.Domain)\$($dono.User)"}else{'?'}))
    }
  } else { Write-Host ("  {0,-12} NAO esta rodando" -f $n) }
}

Titulo "Dependencias de perfil (o que quebra se rodar como LocalSystem)"
foreach ($p in @("$env:USERPROFILE\.ssh\cortex_erp",
                 "C:\Users\inteligencia\.ssh\cortex_erp",
                 "C:\Users\casso\.cloudflared\config-cortex.yml")) {
  Write-Host ("  {0,-55} {1}" -f $p, $(if (Test-Path $p) { 'existe' } else { 'nao existe' }))
}

Titulo "Servicos ja existentes com nome Cortex"
$svc = Get-Service | Where-Object { $_.Name -like '*ortex*' -or $_.DisplayName -like '*ortex*' }
if ($svc) { $svc | Format-Table Name, Status, StartType -AutoSize } else { Write-Host "  nenhum" }

Titulo "Ferramentas disponiveis"
foreach ($e in @('nssm','git','uv')) {
  $cmd = Get-Command $e -ErrorAction SilentlyContinue
  Write-Host ("  {0,-10} {1}" -f $e, $(if ($cmd) { $cmd.Source } else { 'NAO encontrado no PATH' }))
}
Write-Host ""
Write-Host "Copie a saida acima e mande no chat. Nenhuma senha aparece aqui." -ForegroundColor Yellow
