param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$env:TEMP = 'D:\CodexWork\temp'
$env:TMP = $env:TEMP
$env:MPLCONFIGDIR = 'D:\CodexWork\cache\intent-workbench-matplotlib'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:OPENBLAS_NUM_THREADS = '1'
Set-Location -LiteralPath $PSScriptRoot
$researchPython = Join-Path $PSScriptRoot '.venv-research\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $researchPython)) { Write-Output 'Run setup-research.ps1 first.'; exit 1 }
& $researchPython -B (Join-Path $PSScriptRoot 'server.py') --port $Port --open
exit $LASTEXITCODE
