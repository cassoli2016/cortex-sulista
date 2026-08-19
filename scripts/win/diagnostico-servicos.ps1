# CÓRTEX — o que falta saber para virar as 3 tarefas em servico.
#
# Somente leitura. NENHUMA SENHA e lida, pedida ou impressa.
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\win\diagnostico-servicos.ps1

$ErrorActionPreference = 'Continue'
$repo = 'C:\Users\inteligencia\Documents\cortex-sulista'
function Titulo($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }

Titulo "1. Os .vbs que as tarefas realmente executam (data\win)"
$win = Join-Path $repo 'data\win'
if (Test-Path -LiteralPath $win) {
  Get-ChildItem $win -Filter *.vbs | ForEach-Object {
    Write-Host ("  --- {0} ---" -f $_.Name)
    Get-Content $_.FullName | ForEach-Object { Write-Host ("      {0}" -f $_) }
  }
} else { Write-Host "  pasta data\win nao existe" }

Titulo "2. Como o AutoDeploy autentica no GitHub"
Push-Location $repo
Write-Host ("  remote : {0}" -f (git remote get-url origin 2>&1))
Write-Host ("  helper : {0}" -f (git config --get credential.helper 2>&1))
Pop-Location
foreach ($p in @("$env:USERPROFILE\.ssh\id_ed25519", "$env:USERPROFILE\.ssh\id_rsa",
                 "$env:USERPROFILE\.ssh\config")) {
  Write-Host ("  {0,-50} {1}" -f $p, $(if (Test-Path -LiteralPath $p) { 'existe' } else { 'nao existe' }))
}

Titulo "3. Como o painel alcanca o banco do ERP (sem expor senha)"
$env_file = Join-Path $repo '.env'
if (Test-Path -LiteralPath $env_file) {
  Get-Content $env_file | Where-Object { $_ -match '^(POSTGRES_HOST|POSTGRES_PORT|POSTGRES_DB|POSTGRES_USER)=' } |
    ForEach-Object { Write-Host ("  {0}" -f $_) }
  $temToken = (Get-Content $env_file | Where-Object { $_ -match '^GOBRAX_TOKEN=.+' } | Measure-Object).Count
  Write-Host ("  GOBRAX_TOKEN preenchido no .env: {0}" -f $(if ($temToken -gt 0) { 'sim' } else { 'NAO' }))
} else { Write-Host "  .env nao encontrado" }
Write-Host "  (POSTGRES_PASSWORD e demais segredos NAO sao impressos)"

Titulo "4. Config do cloudflared"
foreach ($p in @("$env:USERPROFILE\.cloudflared", "C:\Windows\System32\config\systemprofile\.cloudflared")) {
  if (Test-Path -LiteralPath $p) {
    Write-Host ("  {0}:" -f $p)
    Get-ChildItem $p | ForEach-Object { Write-Host ("      {0}" -f $_.Name) }
  } else { Write-Host ("  {0} nao existe" -f $p) }
}
$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
Write-Host ("  cloudflared no PATH: {0}" -f $(if ($cf) { $cf.Source } else { 'NAO' }))
Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
  $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
  Write-Host ("  em execucao: {0}" -f $cl)
}

Titulo "5. Porta da API e quem escuta"
Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host ("  8010 escutando por pid {0}" -f $_.OwningProcess) }
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
  $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
  Write-Host ("  python pid {0}: {1}" -f $_.Id, $cl)
}
Write-Host ""
Write-Host "Copie a saida e mande no chat. Nenhuma senha aparece aqui." -ForegroundColor Yellow
