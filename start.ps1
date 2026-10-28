param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$env:TEMP = 'D:\CodexWork\temp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = 'D:\CodexWork\cache\pip'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
Set-Location -LiteralPath $PSScriptRoot
$studioPython = Join-Path $PSScriptRoot '.venv-research\Scripts\python.exe'
if (Test-Path -LiteralPath $studioPython) {
    $env:OPENBLAS_NUM_THREADS = '1'
    & $studioPython -B (Join-Path $PSScriptRoot 'server.py') --port $Port --open
} else {
    & python -B (Join-Path $PSScriptRoot 'server.py') --port $Port --open
}
exit $LASTEXITCODE
