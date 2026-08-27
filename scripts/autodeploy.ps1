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
# Escrever no log NUNCA pode derrubar o deploy nem se disfarçar de falha dele.
# O log é lido o tempo todo (tail, editor, monitoramento) e no Windows isso
# basta para o Add-Content esbarrar em "arquivo em uso por outro processo".
# Aconteceu de verdade: um deploy BEM-SUCEDIDO (API no ar, deployed.txt certo)
# registrou "ERRO: o processo não pode acessar o arquivo" porque a gravação da
# linha de sucesso caiu no catch — o oposto do que tinha ocorrido.
function Registrar([string]$m) {
  $linha = ('{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m)
  foreach ($tentativa in 1..5) {
    try {
      Add-Content -Path $log -Value $linha -Encoding utf8 -ErrorAction Stop
      return
    } catch {
      Start-Sleep -Milliseconds (100 * $tentativa)
    }
  }
  # desistiu: segue em silêncio. Perder uma linha de log é irrelevante perto de
  # abortar um deploy que já deu certo.
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
    # A SAIDA DO MERGE E CONFERIDA. Sem isto o script registrava "atualizado"
    # sempre, desse certo ou nao - e um merge recusado virava um log que MENTE.
    # Aconteceu em 27/08/2026: uma alteracao nao commitada em `uv.lock` (uma
    # linha, so o numero de versao) bloqueava o fast-forward, e o log dizia
    # "atualizado c66d740 -> 4332d2e" a cada dois minutos enquanto o HEAD nao
    # saia do lugar. Quem olhasse o log concluiria que o deploy tinha subido.
    # `uv.lock` E GERADO, e e' o proprio deploy que o suja: o `uv sync` daqui
    # de baixo reescreve a linha `version` do pacote para casar com o
    # pyproject, e a alteracao fica pendurada na arvore. Na proxima subida o
    # fast-forward e' RECUSADO por causa dela, e o deploy trava - aconteceu
    # duas vezes em 27/08/2026, uma delas por uma unica linha de diferenca.
    # Alteracao de dependencia de verdade chega COMMITADA; uma pendente aqui e'
    # sempre residuo, entao descartar e' seguro e restaura o unico estado
    # valido, que e' o do origin.
    $sujo = & $git @gitOpt status --porcelain -- uv.lock
    if ($sujo) {
      & $git @gitOpt checkout -- uv.lock
      Registrar 'uv.lock estava modificado na arvore (residuo do uv sync) - descartado antes do merge'
    }
    $saidaMerge = & $git @gitOpt merge --ff-only origin/main 2>&1
    $depois = Git-Texto @('rev-parse', 'HEAD')
    if ($depois -ne $remoto) {
      # O git responde em VARIAS linhas e a segunda e' que traz o nome do
      # arquivo que travou; o log guarda uma linha por registro, entao junta
      # tudo com ' | ' em vez de perder o resto.
      $motivo = (($saidaMerge | Out-String).Trim() -split "`r?`n" -join ' | ')
      # Alteracao local nao commitada e' de longe a causa mais comum, e a saida
      # do git ja nomeia o arquivo - passa adiante inteira, para nao obrigar
      # ninguem a reproduzir o merge na mao so para saber o que travou.
      Registrar ("FALHOU o fast-forward $($local.Substring(0,7)) -> " +
                 "$($remoto.Substring(0,7)); HEAD segue em $($depois.Substring(0,7)). " +
                 "git disse: " + $motivo)
      exit 1
    }
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
    # COMMIT EM EXECUCAO PODE NAO EXISTIR MAIS. Foi o que aconteceu em
    # 25/08/2026: o historico foi reescrito para expurgar planilhas, todos os
    # SHAs mudaram, e o deployed.txt ficou apontando para um commit orfao.
    #
    # A intencao aqui sempre foi tolerar isso ("commit desconhecido = assume
    # que nao mudaram"), mas a implementacao fazia o contrario: no PowerShell
    # 5.1, redirecionar o stderr de um executavel nativo com 2>&1 embrulha
    # cada linha num ErrorRecord, e com $ErrorActionPreference='Stop' isso
    # vira erro TERMINANTE. O git dizia "Not a valid object name" e o deploy
    # inteiro abortava — a cada 2 minutos, por 3 horas, sem reiniciar a API.
    # O sintoma para o usuario era o pior possivel: o frontend NOVO (servido
    # do disco) chamando um backend VELHO, entao a tela existia e a rota dela
    # respondia 404.
    $eapPrev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $conhecido = $false
    try {
      & $git @gitOpt cat-file -e "$rodando^{commit}" 2>$null
      $conhecido = ($LASTEXITCODE -eq 0)
    } catch {
      $conhecido = $false
    } finally {
      $ErrorActionPreference = $eapPrev
    }
    if ($conhecido) {
      $depsMud = [bool]((& $git @gitOpt diff --name-only $rodando $head) -match '(^pyproject\.toml$|^uv\.lock$)')
    } else {
      Registrar "commit em execucao ($($rodando.Substring(0,7))) nao existe mais no repo; seguindo para o restart"
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
      # DUAS TENTATIVAS, e a saida do uv vai INTEIRA para o log quando falha.
      #
      # A causa mais comum aqui e transitoria e nao tem nada a ver com
      # dependencia: `uv sync` sem grupo REMOVE o pytest (correto - producao nao
      # carrega pytest), e a remocao falha com "os error 32" quando alguem esta
      # rodando a suite nesta mesma arvore. Foi o que aconteceu em 27/08/2026,
      # em tres deploys seguidos.
      #
      # Antes, a saida ia para Out-Null e o log dizia so "saiu 2" - sem o
      # motivo, ninguem tinha como saber se era um arquivo travado (inofensivo)
      # ou um pacote que nao instalou (a API sobe e quebra na primeira
      # requisicao que o usar).
      $saidaUv = $null
      foreach ($tentativa in 1, 2) {
        if (Test-Path $uvExe) { $saidaUv = & $uvExe sync 2>&1 }
        elseif (Get-Command uv -ErrorAction SilentlyContinue) { $saidaUv = uv sync 2>&1 }
        else { Registrar "AVISO: uv nao encontrado; dependencias podem estar desatualizadas"; break }
        if (-not $LASTEXITCODE -or $LASTEXITCODE -eq 0) { break }
        if ($tentativa -eq 1) { Start-Sleep -Seconds 5 }
      }
      if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        $txt = (($saidaUv | Out-String).Trim() -split "`r?`n" | Where-Object { $_ -match '\S' })
        $ultimas = ($txt | Select-Object -Last 3) -join ' | '
        Registrar ("AVISO: uv sync saiu $LASTEXITCODE nas 2 tentativas (seguindo assim mesmo): " + $ultimas)
      }
    } catch {
      Registrar ("AVISO: uv sync falhou (seguindo assim mesmo): " + $_.Exception.Message)
    } finally {
      $ErrorActionPreference = $eapPrev
    }

    # O `uv sync` e best-effort, entao ele PODE ter deixado de instalar um
    # pacote novo - e disso a API nao reclama no boot: ela sobe e quebra so na
    # primeira requisicao que usar o pacote, possivelmente dias depois. Uma
    # importacao de teste custa menos de um segundo e transforma isso num aviso
    # no log, no minuto do deploy.
    $pyVenv = Join-Path $repo '.venv\Scripts\python.exe'
    if (Test-Path $pyVenv) {
      # `sys.path` explicito em vez de depender do Set-Location la de cima:
      # a checagem passaria a acusar ModuleNotFoundError em TODO deploy no dia
      # em que alguem mexesse no diretorio de trabalho do script, e um alarme
      # que dispara sempre e' um alarme que ninguem le.
      $chk = & $pyVenv -c "import sys; sys.path.insert(0, sys.argv[1]); import api.main" $repo 2>&1
      if ($LASTEXITCODE -ne 0) {
        $motivo = (($chk | Out-String).Trim() -split "`r?`n" | Where-Object { $_ -match '\S' } |
                   Select-Object -Last 2) -join ' | '
        Registrar ("ERRO: o codigo novo NAO importa neste ambiente - a API vai subir quebrada. " + $motivo)
      }
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
