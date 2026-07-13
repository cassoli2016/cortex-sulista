# CÓRTEX — auto-deploy: sincroniza esta máquina com o GitHub e reinicia a API
# quando há commit novo em origin/main. Roda em background pela tarefa
# "Cortex Sulista - AutoDeploy" (a cada 2 min). Log em logs\autodeploy.log.
#
# Estratégia SEGURA: só aplica fast-forward. Se o histórico local divergir do
# remoto (commits locais não enviados), NÃO force nada — apenas registra e sai,
# para nunca destruir trabalho ou dados de runtime (data\, .env são ignorados).

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$logDir = Join-Path $repo 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir 'autodeploy.log'
function Registrar([string]$m) {
  $linha = ('{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m)
  Add-Content -Path $log -Value $linha -Encoding utf8
}

$git = 'git'
$uvExe = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe"

try {
  & $git fetch --quiet origin main
  $local  = (& $git rev-parse HEAD).Trim()
  $remoto = (& $git rev-parse origin/main).Trim()
  if ($local -eq $remoto) { exit 0 }   # nada novo — silêncio (não polui o log)

  # só aplica se for fast-forward (remoto é descendente do local)
  $base = (& $git merge-base HEAD origin/main).Trim()
  if ($base -ne $local) {
    Registrar "DIVERGENCIA: local=$($local.Substring(0,7)) origin=$($remoto.Substring(0,7)); pull nao aplicado (resolver manualmente)."
    exit 1
  }

  # detecta se dependências mudaram (uv sync só quando necessário)
  $depsMud = (& $git diff --name-only $local $remoto) -match '(^pyproject\.toml$|^uv\.lock$)'

  & $git merge --ff-only --quiet origin/main
  Registrar "atualizado $($local.Substring(0,7)) -> $($remoto.Substring(0,7))"

  if ($depsMud) {
    Registrar "dependencias mudaram -> uv sync"
    if (Test-Path $uvExe) { & $uvExe sync 2>&1 | Out-Null }
    elseif (Get-Command uv -ErrorAction SilentlyContinue) { uv sync 2>&1 | Out-Null }
    else { Registrar "AVISO: uv nao encontrado; dependencias podem estar desatualizadas" }
  }

  # reinicia a API para carregar o código novo (o frontend é servido do disco,
  # mas o backend Python precisa reiniciar)
  $conns = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue
  foreach ($c in $conns) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Milliseconds 800
  Start-ScheduledTask -TaskName 'Cortex Sulista - API'
  Registrar "API reiniciada"
}
catch {
  Registrar ("ERRO: " + $_.Exception.Message)
  exit 1
}
