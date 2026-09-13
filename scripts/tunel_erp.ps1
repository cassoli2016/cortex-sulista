# Túnel SSH ao ERP AVA (réplica de leitura) — deixa 127.0.0.1:15432 apontando
# para o Postgres do ERP atraves de um host de salto (ERP_SSH_DESTINO e
# ERP_TUNEL_ALVO, no .env).
#
# Usa a chave dedicada (scripts\instalar_chave_erp.ps1 instala a chave no ERP).
# Se a chave ainda não estiver instalada, cai para autenticação por senha
# (será pedida no terminal). Para rodar como serviço (sem janela), instale a
# chave e habilite a tarefa "Cortex Sulista - Tunnel ERP".
#
# Uso interativo:  powershell -ExecutionPolicy Bypass -File scripts\tunel_erp.ps1

$ErrorActionPreference = 'Continue'
$ssh = "$env:WINDIR\System32\OpenSSH\ssh.exe"
$key = "$env:USERPROFILE\.ssh\cortex_erp"
$raiz = Split-Path -Parent $PSScriptRoot
$cfg = @{}
$arqEnv = Join-Path $raiz '.env'
if (Test-Path $arqEnv) {
  Get-Content $arqEnv | ForEach-Object { if ($_ -match '^\s*(ERP_[A-Z_]+)\s*=\s*(.*)$') { $cfg[$Matches[1]] = $Matches[2].Trim() } }
}
# Os enderecos vem do .env e NAO ficam aqui: o repositorio e publico.
$destino = $cfg['ERP_SSH_DESTINO']
$alvo = $cfg['ERP_TUNEL_ALVO']
if (-not $destino -or -not $alvo) {
  Write-Host "[tunel-erp] faltam ERP_SSH_DESTINO (usuario@host) e ERP_TUNEL_ALVO (host:porta) no .env" -ForegroundColor Red
  exit 1
}

$temChave = Test-Path $key
$argsBase = @(
  '-N',
  '-L', "15432:$alvo",
  '-o', 'ServerAliveInterval=30',
  '-o', 'ServerAliveCountMax=3',
  '-o', 'ExitOnForwardFailure=yes',
  '-o', 'StrictHostKeyChecking=accept-new',
  '-p', '22'
)
if ($temChave) {
  $argsBase = @('-i', $key, '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes') + $argsBase
}

while ($true) {
  $modo = if ($temChave) { 'chave' } else { 'senha' }
  Write-Host "[tunel-erp] conectando a $destino (Tailscale, via $modo)..." -ForegroundColor Yellow
  & $ssh @argsBase $destino
  Write-Host "[tunel-erp] conexão encerrada — nova tentativa em 5s (Ctrl+C para sair)" -ForegroundColor Red
  Start-Sleep -Seconds 5
}
