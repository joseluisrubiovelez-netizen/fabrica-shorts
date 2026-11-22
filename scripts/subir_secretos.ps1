# Sube a GitHub (Settings > Secrets > Actions) cada clave con valor de tu archivo .env.
# Lo ejecutas TU, una vez (y otra vez cuando cambies alguna clave):
#     .\scripts\subir_secretos.ps1
# Requiere GitHub CLI: winget install GitHub.cli   y luego:   gh auth login
param([string]$Repo = "joseluisrubiovelez-netizen/fabrica-shorts", [string]$Modo = "review")
$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Output "Falta GitHub CLI. Instala con:  winget install GitHub.cli   (y abre una terminal nueva)"
    exit 1
}
gh auth status *> $null
if ($LASTEXITCODE -ne 0) { Write-Output "Primero inicia sesion:  gh auth login"; exit 1 }

$subidos = 0
foreach ($linea in Get-Content .env -Encoding UTF8) {
    if ($linea -match '^\s*#' -or $linea -notmatch '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') { continue }
    $nombre = $Matches[1]; $valor = $Matches[2].Trim()
    if ($nombre -eq "FABRICA_MODO" -or $valor -eq "") { continue }
    $valor | gh secret set $nombre --repo $Repo
    if ($LASTEXITCODE -eq 0) { Write-Output "OK  $nombre"; $subidos++ } else { Write-Output "ERROR  $nombre" }
}
gh variable set FABRICA_MODO --body $Modo --repo $Repo
Write-Output ""
Write-Output "Listo: $subidos secretos subidos y FABRICA_MODO=$Modo."
