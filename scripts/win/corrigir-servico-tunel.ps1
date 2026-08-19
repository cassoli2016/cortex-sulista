# CORTEX -- corrige o servico do cloudflared que instala mas nao inicia.
#
# CAUSA, confirmada por sc.exe qc Cloudflared:
#   NOME_DO_CAMINHO_BINARIO : "C:\Program Files (x86)\cloudflared\cloudflared.exe"
# O 'service install' registra o binario SEM ARGUMENTOS. Sem --config e sem
# 'tunnel run', o cloudflared roda sem comando, sai imediatamente, e o Windows
# reporta falha ao iniciar.
#
# ESTE SCRIPT SE DESFAZ SOZINHO: se o painel publico nao voltar, ele reabilita a
# tarefa antiga do tunel antes de terminar. Voce nao fica com o painel fora.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\win\corrigir-servico-tunel.ps1

$ErrorActionPreference = 'Continue'
$exe    = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
$sysCfg = 'C:\Windows\System32\config\systemprofile\.cloudflared'
$yml    = Join-Path $sysCfg 'config.yml'
$URL    = 'https://cortex.cassolitech.com.br/'
$TAREFA = 'Cortex Sulista - Tunnel'

function Passo($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "   OK   $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   !    $t" -ForegroundColor Yellow }

function PainelNoAr([int]$tentativas = 10) {
  foreach ($i in 1..$tentativas) {
    Start-Sleep -Seconds 3
    $r = try { Invoke-WebRequest $URL -UseBasicParsing -TimeoutSec 20 } catch { $null }
    if ($r -and $r.StatusCode -eq 200) { return $true }
    Write-Host ("   tentativa {0}/{1}: ainda nao" -f $i, $tentativas)
  }
  return $false
}

function VoltarParaTarefa($motivo) {
  Aviso $motivo
  Passo 'Revertendo para a tarefa antiga (o painel volta)'
  Stop-Service Cloudflared -Force -ErrorAction SilentlyContinue
  Set-Service  Cloudflared -StartupType Disabled -ErrorAction SilentlyContinue
  Enable-ScheduledTask -TaskName $TAREFA -ErrorAction SilentlyContinue | Out-Null
  Start-ScheduledTask  -TaskName $TAREFA -ErrorAction SilentlyContinue
  if (PainelNoAr 10) { Ok 'painel de volta pela tarefa antiga' }
  else { Aviso 'painel AINDA fora -- rode: scripts\win\reverter-sem-login.ps1 -Tunel' }
  exit 1
}

Passo '1. Conferindo o que esta registrado hoje'
if (-not (Test-Path -LiteralPath $exe)) { Aviso "cloudflared nao encontrado em $exe"; exit 1 }
if (-not (Test-Path -LiteralPath $yml)) { Aviso "config nao encontrado em $yml"; exit 1 }
& sc.exe qc Cloudflared | Select-String 'BIN' | ForEach-Object { Write-Host "      $_" }

Passo '2. Registrando o comando completo no servico'
# sc.exe exige espaco depois do '=' e aspas internas escapadas
$binPath = '"{0}" --config "{1}" tunnel run' -f $exe, $yml
& sc.exe config Cloudflared binPath= "$binPath" | ForEach-Object { Write-Host "      $_" }
& sc.exe qc Cloudflared | Select-String 'BIN' | ForEach-Object { Write-Host "      $_" }
Ok 'binPath atualizado'

Passo '3. Tirando a tarefa antiga do caminho'
# duas instancias do MESMO tunel disputam a conexao: a tarefa sai antes
Stop-ScheduledTask  -TaskName $TAREFA -ErrorAction SilentlyContinue
Disable-ScheduledTask -TaskName $TAREFA -ErrorAction SilentlyContinue | Out-Null
Get-Process cloudflared -ErrorAction SilentlyContinue |
  ForEach-Object { Ok "encerrando cloudflared pid $($_.Id)"; Stop-Process -Id $_.Id -Force }
Start-Sleep -Seconds 3

Passo '4. Subindo o servico'
Set-Service Cloudflared -StartupType Automatic
Start-Service Cloudflared -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5
$svc = Get-Service Cloudflared -ErrorAction SilentlyContinue
if (-not $svc -or $svc.Status -ne 'Running') {
  VoltarParaTarefa ("o servico nao iniciou (status: {0})" -f $(if ($svc) { $svc.Status } else { 'inexistente' }))
}
Ok 'servico Cloudflared rodando'

Passo '5. O painel responde pelo tunel do servico?'
if (-not (PainelNoAr 12)) {
  VoltarParaTarefa 'o servico esta rodando mas o painel nao respondeu'
}
Ok 'painel publico respondendo 200 pelo servico'

Passo '6. Estado final'
& sc.exe qc Cloudflared | Select-String 'BIN|INICIO|START' | ForEach-Object { Write-Host "      $_" }
Write-Host ""
Write-Host "Agora o teste que vale: FACA LOGOFF e abra o painel de outro" -ForegroundColor Yellow
Write-Host "dispositivo. Se abrir, as 3 estao rodando sem login." -ForegroundColor Yellow
Write-Host "Se falhar: scripts\win\reverter-sem-login.ps1 -Tunel" -ForegroundColor Yellow
