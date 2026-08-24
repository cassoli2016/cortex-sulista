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
#
# ---------------------------------------------------------------------------
# POR QUE `-c safe.directory` EM TODO COMANDO GIT (não é decoração)
#
# As tarefas rodam como SISTEMA, e o repositório pertence a
# `sulistalocal\inteligencia`. Desde o CVE-2022-24765 o git RECUSA operar em
# repositório de outro dono ("detected dubious ownership"): manda o aviso para
# o stderr e devolve VAZIO no stdout. O script então fazia `$null.Trim()` e
# morria com "Não é possível chamar um método em uma expressão de valor nulo"
# — mensagem que não diz nada sobre a causa. Resultado: o auto-deploy ficou
# quebrado silenciosamente, falhando a cada 2 min, e o restart da API virou
# tarefa manual.
#
# `-c safe.directory=<repo>` resolve no ESCOPO DE COMANDO, que é o que o git
# aceita para essa chave (config do próprio repositório é ignorada de
# propósito, senão um repo hostil se auto-autorizaria). Preferido a
# `git config --system`, que exigiria admin e teria de ser refeito a cada
# máquina nova.
# ---------------------------------------------------------------------------

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

# prefixo aplicado a TODA chamada git (ver bloco acima)
$git = 'git'
$gitOpt = @('-c', "safe.directory=$repo")

# Encapsula a chamada e FALHA ALTO quando o git não devolve nada. Sem isto,
# qualquer recusa do git (dono, repo corrompido, ref ausente) chegava como
# erro de null lá na frente, longe da causa.
function Git-Texto([string[]]$argumentos) {
  $saida = & $git @gitOpt @argumentos 2>&1
  $texto = ($saida | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }) -join "`n"
  if ([string]::IsNullOrWhiteSpace($texto)) {
    $motivo = ($saida | Out-String).Trim()
    throw ("git " + ($argumentos -join ' ') + " nao devolveu saida. git disse: " + $motivo)
  }
  return $texto.Trim()
}

$uvExe = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe"
# Como SISTEMA, $env:LOCALAPPDATA aponta para o systemprofile e o uv instalado
# no perfil do usuário não está lá — nem no PATH. Sem este fallback, mudança de
# dependência passava batida com um simples AVISO e a API subia sem o pacote
# novo (falha só na primeira requisição que o usasse).
if (-not (Test-Path $uvExe)) {
  $alt = Get-ChildItem 'C:\Users\*\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_*\uv.exe' -ErrorAction SilentlyContinue |
         Select-Object -First 1
  if ($alt) { $uvExe = $alt.FullName }
}

try {
  & $git @gitOpt fetch --quiet origin main
  $local  = Git-Texto @('rev-parse', 'HEAD')
  $remoto = Git-Texto @('rev-parse', 'origin/main')

  if ($local -ne $remoto) {
    # só aplica se for fast-forward (remoto é descendente do local)
    $base = Git-Texto @('merge-base', 'HEAD', 'origin/main')
    if ($base -ne $local) {
      Registrar "DIVERGENCIA: local=$($local.Substring(0,7)) origin=$($remoto.Substring(0,7)); pull nao aplicado (resolver manualmente)."
      exit 1
    }
    & $git @gitOpt merge --ff-only --quiet origin/main
    Registrar "atualizado $($local.Substring(0,7)) -> $($remoto.Substring(0,7))"
  }

  # a API precisa reiniciar? compara o HEAD com o commit em execução
  $head = Git-Texto @('rev-parse', 'HEAD')
  $estadoArq = Join-Path $logDir 'deployed.txt'
  $rodando = ''
  if (Test-Path $estadoArq) {
    $conteudo = Get-Content $estadoArq -Raw
    if ($conteudo) { $rodando = $conteudo.Trim() }
  }
  if ($rodando -eq $head) { exit 0 }   # nada novo — silêncio (não polui o log)

  # detecta se dependências mudaram desde o commit em execução (uv sync só
  # quando necessário; commit desconhecido/podado = assume que não mudaram)
  $depsMud = $false
  if ($rodando) {
    & $git @gitOpt cat-file -e "$rodando^{commit}" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
      $depsMud = [bool]((& $git @gitOpt diff --name-only $rodando $head) -match '(^pyproject\.toml$|^uv\.lock$)')
    }
  }
  if ($depsMud) {
    Registrar "dependencias mudaram -> uv sync"
    # uv escreve progresso no stderr e as vezes sai != 0 por causas benignas;
    # com ErrorActionPreference=Stop isso ABORTAVA o deploy antes de reiniciar
    # a API. uv sync e best-effort: loga e segue para o restart.
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

  # Confere que a API voltou ANTES de gravar deployed.txt. Gravar sem conferir
  # marcaria o commit como implantado mesmo com a API fora do ar, e o ciclo
  # seguinte veria "nada novo" e nunca mais tentaria — deixando o painel morto
  # em silêncio.
  $voltou = $false
  foreach ($tentativa in 1..20) {
    Start-Sleep -Milliseconds 750
    if (Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue) { $voltou = $true; break }
  }
  if ($voltou) {
    Set-Content -Path $estadoArq -Value $head -Encoding Ascii
    Registrar "API reiniciada em $($head.Substring(0,7))"
  } else {
    Registrar "ERRO: API nao voltou a escutar na porta 8010 apos o restart em $($head.Substring(0,7)); deployed.txt nao atualizado (vai tentar de novo)"
    exit 1
  }
}
catch {
  Registrar ("ERRO: " + $_.Exception.Message)
  exit 1
}
