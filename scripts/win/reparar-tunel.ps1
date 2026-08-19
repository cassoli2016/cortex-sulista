# CORTEX -- diagnostica e repara o tunel cloudflared rodando como servico.
#
# Sintoma que isto resolve: painel publico devolvendo 530 / "Error 1033
# Cloudflare Tunnel error" depois de virar o tunel para servico.
#
# Causa provavel: o config-cortex.yml aponta credentials-file para
# C:\Users\inteligencia\.cloudflared\<uuid>.json, mas o servico roda como
# LocalSystem e le a config do perfil DELE. Se o caminho nao for reescrito, o
# servico sobe e nao autentica -- o processo existe, o tunel nao conecta.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\win\reparar-tunel.ps1

$ErrorActionPreference = 'Continue'
$sysCfg = 'C:\Windows\System32\config\systemprofile\.cloudflared'
$usrCfg = 'C:\Users\inteligencia\.cloudflared'
$yml    = Join-Path $sysCfg 'config-cortex.yml'

function Passo($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "   OK   $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   !    $t" -ForegroundColor Yellow }

Passo '1. Estado do servico'
$svc = Get-Service | Where-Object { $_.Name -like '*cloudflare*' } | Select-Object -First 1
if ($svc) {
  Write-Host ("   nome={0}  status={1}  inicio={2}" -f $svc.Name, $svc.Status, $svc.StartType)
} else { Aviso 'nenhum servico cloudflared encontrado' }

Passo '2. Config que o servico esta lendo'
if (Test-Path -LiteralPath $yml) {
  Get-Content $yml | ForEach-Object { Write-Host "      $_" }
} else { Aviso "$yml nao existe" }

Passo '3. Arquivos no perfil do sistema'
if (Test-Path -LiteralPath $sysCfg) {
  Get-ChildItem $sysCfg | ForEach-Object { Write-Host ("      {0}" -f $_.Name) }
} else { Aviso "$sysCfg nao existe" }

Passo '4. Reparando o caminho da credencial'
if (Test-Path -LiteralPath $yml) {
  $texto = Get-Content $yml -Raw
  $novo = $texto -replace [regex]::Escape($usrCfg), $sysCfg
  if ($novo -ne $texto) {
    Copy-Item $yml "$yml.bak" -Force
    Set-Content -Path $yml -Value $novo -Encoding utf8
    Ok "credentials-file reapontado para o perfil do sistema (backup em config-cortex.yml.bak)"
  } else {
    Ok 'o config nao referencia o perfil do usuario -- nada a reescrever'
  }
  # garante que o JSON de credencial esta mesmo la
  Get-ChildItem $usrCfg -Filter *.json -ErrorAction SilentlyContinue | ForEach-Object {
    $destino = Join-Path $sysCfg $_.Name
    if (-not (Test-Path -LiteralPath $destino)) {
      Copy-Item $_.FullName $destino -Force; Ok "credencial copiada: $($_.Name)"
    }
  }
}

Passo '5. Reiniciando o servico'
if ($svc) {
  Restart-Service $svc.Name -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 5
  $svc = Get-Service -Name $svc.Name
  Write-Host ("   status agora: {0}" -f $svc.Status)
}

Passo '6. O painel voltou?'
$ok = $false
foreach ($i in 1..10) {
  Start-Sleep -Seconds 3
  $r = try { Invoke-WebRequest 'https://cortex.cassolitech.com.br/' -UseBasicParsing -TimeoutSec 20 } catch { $null }
  if ($r -and $r.StatusCode -eq 200) { $ok = $true; break }
  Write-Host ("   tentativa {0}: ainda nao" -f $i)
}
if ($ok) {
  Ok 'painel publico respondendo 200 -- tunel reparado'
  Write-Host ""
  Write-Host "Agora repita o teste: logoff e abrir de outro dispositivo." -ForegroundColor Yellow
} else {
  Aviso 'o painel continua fora. Ultimas linhas do log do servico:'
  Get-EventLog -LogName Application -Source 'cloudflared*' -Newest 15 -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host ("      {0}  {1}" -f $_.TimeGenerated, ($_.Message -split "`n")[0]) }
  Write-Host ""
  Write-Host "SE PRECISAR DO PAINEL AGORA, reverta:" -ForegroundColor Yellow
  Write-Host "  powershell -File scripts\win\reverter-sem-login.ps1" -ForegroundColor Yellow
  Write-Host "Isso volta o tunel para a tarefa antiga (que exige login, mas funciona)." -ForegroundColor Yellow
}
