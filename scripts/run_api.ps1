# Sobe o CÓRTEX localmente (Windows). Pré-requisito: túnel SSH ativo
# (scripts\tunel_erp.ps1) para o banco responder — a página abre mesmo sem ele.
#
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\run_api.ps1

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# uv instalado via winget (fora do PATH de sessões antigas)
$uvDir = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { $env:Path += ";$uvDir" }

# Avisa (mas não bloqueia) se o túnel do ERP não está de pé
$tunel = Test-NetConnection -ComputerName 127.0.0.1 -Port 15432 -WarningAction SilentlyContinue
if (-not $tunel.TcpTestSucceeded) {
    Write-Host "AVISO: túnel SSH do ERP não detectado em 127.0.0.1:15432." -ForegroundColor Yellow
    Write-Host "       Abra em outra janela: powershell -File scripts\tunel_erp.ps1" -ForegroundColor Yellow
}

# Porta 8010: a 3000 é do HS Sistema e a 8000 está reservada no túnel mn-app.
Write-Host "CÓRTEX -> http://127.0.0.1:8010" -ForegroundColor Green
uv run uvicorn api.main:app --host 127.0.0.1 --port 8010
