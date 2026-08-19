# CORTEX -- limpa tarefas duplicadas com nome corrompido e restaura os nomes certos.
#
# O QUE ACONTECEU: o reverter-sem-login.ps1 derivava o nome da tarefa do nome do
# ARQUIVO de backup. Como "Cortex Sulista - API" vira "Cortex_Sulista___API" no
# arquivo, o caminho de volta produzia "Cortex Sulista   API" -- com tres
# espacos. O resultado foram tarefas novas com nome errado convivendo com (ou
# substituindo) as originais.
#
# Este script LISTA tudo primeiro e so age com sua confirmacao.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\win\limpar-tarefas-duplicadas.ps1

$ErrorActionPreference = 'Continue'
$repo = 'C:\Users\inteligencia\Documents\cortex-sulista'
$backup = Join-Path $repo 'data\win\backup-tarefas'

function Passo($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "   OK   $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   !    $t" -ForegroundColor Yellow }

Passo '1. Tarefas do Cortex existentes hoje'
$todas = Get-ScheduledTask | Where-Object { $_.TaskName -like '*ortex*' }
if (-not $todas) { Aviso 'nenhuma tarefa do Cortex encontrada'; }
$todas | ForEach-Object {
  $p = $_.Principal
  $acao = ($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join ' | '
  Write-Host ("   [{0}] '{1}'" -f $_.State, $_.TaskName)
  Write-Host ("        conta={0} logon={1}" -f $p.UserId, $p.LogonType)
  Write-Host ("        acao={0}" -f $acao)
}

Passo '2. Nomes corretos, lidos do backup'
$corretos = @()
if (Test-Path -LiteralPath $backup) {
  Get-ChildItem $backup -Filter *.xml | ForEach-Object {
    $x = [xml](Get-Content $_.FullName -Raw)
    $uri = $x.Task.RegistrationInfo.URI
    if ($uri) { $corretos += $uri.TrimStart('\'); Write-Host ("   {0}" -f $uri.TrimStart('\')) }
  }
} else { Aviso "sem backup em $backup" }

Passo '3. O que sobra (nome nao bate com nenhum backup)'
$suspeitas = $todas | Where-Object { $corretos -notcontains $_.TaskName }
if ($suspeitas) {
  $suspeitas | ForEach-Object { Write-Host ("   candidata a remocao: '{0}'" -f $_.TaskName) }
  Write-Host ""
  $resp = Read-Host "Remover as tarefas listadas acima? (digite SIM para confirmar)"
  if ($resp -eq 'SIM') {
    $suspeitas | ForEach-Object {
      Stop-ScheduledTask -TaskName $_.TaskName -ErrorAction SilentlyContinue
      Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false -ErrorAction SilentlyContinue
      Ok ("removida: {0}" -f $_.TaskName)
    }
  } else { Aviso 'nada removido' }
} else { Ok 'nenhuma tarefa com nome estranho' }

Passo '4. Restaurando as que faltam, com o nome certo'
foreach ($nome in $corretos) {
  if (Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue) {
    Ok "ja existe: $nome"; continue
  }
  $arq = Get-ChildItem $backup -Filter *.xml | Where-Object {
    ([xml](Get-Content $_.FullName -Raw)).Task.RegistrationInfo.URI.TrimStart('\') -eq $nome
  } | Select-Object -First 1
  if ($arq) {
    try {
      Register-ScheduledTask -TaskName $nome -Xml (Get-Content $arq.FullName -Raw) `
        -User 'inteligencia' -ErrorAction Stop | Out-Null
      Ok "restaurada com o nome correto: $nome"
    } catch {
      Aviso "falhou ao restaurar $nome : $($_.Exception.Message)"
    }
  }
}

Passo '5. Estado final'
Get-ScheduledTask | Where-Object { $_.TaskName -like '*ortex*' } | ForEach-Object {
  Write-Host ("   [{0}] '{1}'  {2}/{3}" -f $_.State, $_.TaskName,
              $_.Principal.UserId, $_.Principal.LogonType)
}
