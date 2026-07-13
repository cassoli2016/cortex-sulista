# Instala a chave pública do CÓRTEX no servidor do ERP (Windows/OpenSSH), para
# que o túnel rode sem senha (como serviço). Você digita a senha UMA vez, aqui,
# só para copiar a chave — ela nunca é gravada em lugar nenhum.
#
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\instalar_chave_erp.ps1

$ErrorActionPreference = 'Stop'
$destino = 'sulistalocal\inteligencia@100.120.225.5'
$pub = "$env:USERPROFILE\.ssh\cortex_erp.pub"
if (-not (Test-Path $pub)) { throw "Chave pública não encontrada: $pub" }

# Script que roda NO servidor do ERP: descobre se a conta é administradora e
# grava a chave no authorized_keys correto (admin usa administrators_authorized_keys).
$remoto = @'
$ErrorActionPreference='Stop'
$key = [Console]::In.ReadToEnd().Trim()
$sidAdmin = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
$grupos = ([Security.Principal.WindowsIdentity]::GetCurrent()).Groups
$ehAdmin = $grupos -contains $sidAdmin
if ($ehAdmin) {
  $arq = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
} else {
  $dir = Join-Path $env:USERPROFILE '.ssh'
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
  $arq = Join-Path $dir 'authorized_keys'
}
$atual = ''
if (Test-Path $arq) { $atual = Get-Content $arq -Raw }
if ($atual -notlike ('*' + $key + '*')) {
  Add-Content -Path $arq -Value $key -Encoding ascii
  $acao = 'chave adicionada'
} else { $acao = 'chave ja presente' }
if ($ehAdmin) {
  icacls $arq /inheritance:r /grant 'Administrators:F' 'SYSTEM:F' | Out-Null
}
Write-Output ("OK: $acao em $arq (admin=$ehAdmin)")
'@

$b64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($remoto))
Write-Host "Copiando a chave para o ERP — digite a senha de '$destino' quando pedir..." -ForegroundColor Yellow
Get-Content $pub -Raw | ssh $destino "powershell -NoProfile -EncodedCommand $b64"

Write-Host "`nTestando login por chave (sem senha)..." -ForegroundColor Yellow
$teste = ssh -i "$env:USERPROFILE\.ssh\cortex_erp" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 $destino "echo CHAVE_OK"
if ($teste -match 'CHAVE_OK') {
  Write-Host "SUCESSO: o túnel já pode rodar sem senha." -ForegroundColor Green
} else {
  Write-Host "ATENÇÃO: o teste por chave não confirmou. Saída: $teste" -ForegroundColor Red
}
