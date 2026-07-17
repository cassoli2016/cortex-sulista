# CÓRTEX — auto-deploy: sincroniza esta máquina com o GitHub e reinicia a API
# quando o código em execução ficou para trás. Roda em background pela tarefa
# "Cortex Sulista - AutoDeploy" (a cada 2 min). Log em logs\autodeploy.log.
#
# Estratégia SEGURA: só aplica fast-forward. Se o histórico local divergir do
# remoto (commits locais não enviados), NÃO force nada — apenas registra e sai,
# para nunca destruir trabalho ou dados de runtime (data\, .env são ignorados).
#
# O reinício da API é decidido pelo arquivo logs\deployed.txt (commit com que
# a API foi reiniciada pela última vez): qualquer HEAD diferente dele reinicia,
# inclusive commits feitos NESTA máquina (local == origin, sem pull).

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

  if ($local -ne $remoto) {
    # só aplica se for fast-forward (remoto é descendente do local)
    $base = (& $git merge-base HEAD origin/main).Trim()
    if ($base -ne $local) {
      Registrar "DIVERGENCIA: local=$($local.Substring(0,7)) origin=$($remoto.Substring(0,7)); pull nao aplicado (resolver manualmente)."
      exit 1
    }
    & $git merge --ff-only --quiet origin/main
    Registrar "atualizado $($local.Substring(0,7)) -> $($remoto.Substring(0,7))"
  }

  # a API precisa reiniciar? compara o HEAD com o commit em execução
  $head = (& $git rev-parse HEAD).Trim()
  $estadoArq = Join-Path $logDir 'deployed.txt'
  $rodando = ''
  if (Test-Path $estadoArq) { $rodando = (Get-Content $estadoArq -Raw).Trim() }
  if ($rodando -eq $head) { exit 0 }   # nada novo — silêncio (não polui o log)

  # detecta se dependências mudaram desde o commit em execução (uv sync só
  # quando necessário; commit desconhecido/podado = assume que não mudaram)
  $depsMud = $false
  if ($rodando) {
    & $git cat-file -e "$rodando^{commit}"
    if ($LASTEXITCODE -eq 0) {
      $depsMud = (& $git diff --name-only $rodando $head) -match '(^pyproject\.toml$|^uv\.lock$)'
    }
  }
  if ($depsMud) {
    Registrar "dependencias mudaram -> uv sync"
    # uv escreve progresso no stderr e as vezes sai != 0 por causas benignas;
    # com ErrorActionPreference=Stop (+ PS 7.4) isso ABORTAVA o deploy antes de
    # reiniciar a API. uv sync e best-effort: loga e segue para o restart.
    $eapPrev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
      if (Test-Path $uvExe) { & $uvExe sync 2>&1 | Out-Null }
      elseif (Get-Command uv -ErrorAction SilentlyContinue) { uv sync 2>&1 | Out-Null }
      else { Registrar "AVISO: uv nao encontrado; dependencias podem estar desatualizadas" }
      if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { Registrar "AVISO: uv sync saiu $LASTEXITCODE (seguindo assim mesmo)" }
    } catch {
      Registrar ("AVISO: uv sync falhou (seguindo assim mesmo): " + $_.Exception.Message)
    } finally {
      $ErrorActionPreference = $eapPrev
    }
  }

  # reinicia a API para carregar o código novo (o frontend é servido do disco,
  # mas o backend Python precisa reiniciar)
  $conns = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue
  foreach ($c in $conns) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Milliseconds 800
  Start-ScheduledTask -TaskName 'Cortex Sulista - API'
  Set-Content -Path $estadoArq -Value $head -Encoding Ascii
  Registrar "API reiniciada em $($head.Substring(0,7))"
}
catch {
  Registrar ("ERRO: " + $_.Exception.Message)
  exit 1
}
