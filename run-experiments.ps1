param([ValidateSet('development','evaluation')][string]$Split = 'evaluation')
$ErrorActionPreference = 'Stop'
$env:TEMP = 'D:\CodexWork\temp'
$env:TMP = $env:TEMP
$env:MPLCONFIGDIR = 'D:\CodexWork\cache\intent-workbench-matplotlib'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
Set-Location -LiteralPath $PSScriptRoot
$researchPython = Join-Path $PSScriptRoot '.venv-research\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $researchPython)) { Write-Output 'Run setup-research.ps1 first.'; exit 1 }
$runDirectory = Join-Path $PSScriptRoot ('experiments\runs\' + (Get-Date -Format 'yyyyMMddTHHmmssfff') + '-' + $Split)
& $researchPython -B -m research.experiment --split $Split --output $runDirectory
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $researchPython -B -m research.report $runDirectory --publish
exit $LASTEXITCODE
