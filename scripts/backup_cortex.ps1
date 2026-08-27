# Backup do banco local do CORTEX (PostgreSQL).
#
# POR QUE ISTO EXISTE ANTES DO PRIMEIRO STORE MIGRAR: enquanto o dado morava em
# SQLite, backup era copiar um arquivo - qualquer copia da pasta data/ servia.
# Com o Postgres isso deixa de ser verdade, e a mudanca PIORARIA a seguranca do
# dado se este script viesse depois. Ver docs/MIGRACAO_POSTGRES.md, secao 2.
#
# Formato CUSTOM (-Fc), nao SQL puro: comprime, permite restaurar tabela
# isolada e e o que o pg_restore espera. Restaurar tudo:
#   pg_restore -h 127.0.0.1 -p 5432 -U cortex -d cortex --clean <arquivo>
# Restaurar UMA tabela (o caso comum de "apaguei sem querer"):
#   pg_restore -h ... -U cortex -d cortex --data-only -t rntrc_transportador <arquivo>
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File scripts\backup_cortex.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\backup_cortex.ps1 -Conferir

param([switch]$Conferir)

$ErrorActionPreference = 'Stop'
$repo    = Split-Path -Parent $PSScriptRoot
$destino = Join-Path $repo 'data\backup'
$logDir  = Join-Path $repo 'logs'
foreach ($d in @($destino, $logDir)) {
  if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force $d | Out-Null }
}
$logFile = Join-Path $logDir 'backup-cortex.log'
function Log([string]$m) {
  $linha = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m
  Add-Content -Path $logFile -Value $linha -Encoding utf8
  Write-Host $m
}

# As credenciais saem do .env, nunca da linha de comando: argumento de processo
# e visivel para qualquer usuario da maquina no gerenciador de tarefas.
$envFile = Join-Path $repo '.env'
if (-not (Test-Path $envFile)) { Log 'ERRO: .env nao encontrado'; exit 1 }
$cfg = @{}
foreach ($linha in Get-Content $envFile -Encoding utf8) {
  if ($linha -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
    $cfg[$Matches[1]] = $Matches[2].Trim()
  }
}
if (-not $cfg['CORTEX_PG_PASSWORD']) {
  Log 'banco local nao configurado (sem CORTEX_PG_PASSWORD) - nada a fazer'
  exit 0
}

$pgHost = if ($cfg['CORTEX_PG_HOST']) { $cfg['CORTEX_PG_HOST'] } else { '127.0.0.1' }
$pgPort = if ($cfg['CORTEX_PG_PORT']) { $cfg['CORTEX_PG_PORT'] } else { '5432' }
$pgDb   = if ($cfg['CORTEX_PG_DB'])   { $cfg['CORTEX_PG_DB']   } else { 'cortex' }
$pgUser = if ($cfg['CORTEX_PG_USER']) { $cfg['CORTEX_PG_USER'] } else { 'cortex' }

# pg_dump da MESMA major do servidor. Versao mais nova le servidor mais velho,
# mas o contrario nao: fixar a 17 evita o "server version mismatch" no dia em
# que alguem instalar outra major na maquina.
$dump = 'C:\Program Files\PostgreSQL\17\bin\pg_dump.exe'
if (-not (Test-Path $dump)) { Log "ERRO: pg_dump nao encontrado em $dump"; exit 1 }

if ($Conferir) {
  $arquivos = Get-ChildItem $destino -Filter 'cortex-*.dump' -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending
  if (-not $arquivos) { Write-Host 'nenhum backup ainda'; exit 0 }
  $u = $arquivos[0]
  $horas = [math]::Round(((Get-Date) - $u.LastWriteTime).TotalHours, 1)
  Write-Host ("ultimo: {0} - {1:N0} KB - ha {2} h - {3} arquivo(s) guardado(s)" -f `
              $u.Name, ($u.Length / 1KB), $horas, $arquivos.Count)
  exit 0
}

$carimbo = Get-Date -Format 'yyyy-MM-dd_HHmm'
$saida   = Join-Path $destino "cortex-$carimbo.dump"
$env:PGPASSWORD = $cfg['CORTEX_PG_PASSWORD']
try {
  & $dump -h $pgHost -p $pgPort -U $pgUser -d $pgDb -Fc -f $saida
  if ($LASTEXITCODE -ne 0) { Log "ERRO: pg_dump saiu com $LASTEXITCODE"; exit 1 }
} finally {
  # a variavel morre com o processo, mas limpar e barato e o habito e o certo
  Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}

$kb = [math]::Round((Get-Item $saida).Length / 1KB)
Log "backup ok: $(Split-Path -Leaf $saida) ($kb KB)"

# RETENCAO: 14 dias. Backup que enche o disco derruba o servidor inteiro, e ai
# o remedio virou a doenca. Guardar mais que isso exige destino fora da maquina,
# que e outro assunto - este backup protege contra ERRO, nao contra incendio.
$corte = (Get-Date).AddDays(-14)
$velhos = Get-ChildItem $destino -Filter 'cortex-*.dump' | Where-Object { $_.LastWriteTime -lt $corte }
foreach ($v in $velhos) { Remove-Item $v.FullName -Force; Log "removido antigo: $($v.Name)" }
