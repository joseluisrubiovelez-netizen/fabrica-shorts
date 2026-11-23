# Equivalente a Makefile para Windows sin make.  Uso:  .\make.ps1 setup | run | test | dry-run | estado
param([Parameter(Position = 0)][string]$Orden = "help")
$ErrorActionPreference = "Continue"  # Piper escribe INFO por stderr; no es un error
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Set-Location $PSScriptRoot

switch ($Orden) {
    "setup" {
        python -m venv .venv
        & $py -m pip install --upgrade pip
        & $py -m pip install -r requirements.txt
        & $py -m piper.download_voices --download-dir models es_ES-davefx-medium
        & $py -m fabrica.profundidad descargar
        if (-not (Test-Path .env)) { Copy-Item .env.example .env }
        & $py -m fabrica verificar
    }
    "run"      { & $py -m fabrica ciclo }
    "dry-run"  { & $py -m fabrica --modo dry-run generar --n 1 }
    "generar"  { & $py -m fabrica generar --n 1 }
    "test"     { & $py -m pytest -q tests }
    "estado"   { & $py -m fabrica estado }
    "informe"  { & $py -m fabrica informe }
    "verificar" { & $py -m fabrica verificar }
    default    { Write-Output "Ordenes: setup, run, dry-run, generar, test, estado, informe, verificar" }
}
