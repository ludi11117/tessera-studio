$ErrorActionPreference = 'Stop'
$env:TEMP = 'D:\CodexWork\temp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = 'D:\CodexWork\cache\pip'
$env:PYTHONDONTWRITEBYTECODE = '1'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
Set-Location -LiteralPath $PSScriptRoot
$researchPython = Join-Path $PSScriptRoot '.venv-research\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $researchPython)) { & python -m venv (Join-Path $PSScriptRoot '.venv-research'); if ($LASTEXITCODE) { exit $LASTEXITCODE } }
$requirementsPath = Join-Path $PSScriptRoot 'requirements-research.lock'
if (-not (Test-Path -LiteralPath $requirementsPath)) { $requirementsPath = Join-Path $PSScriptRoot 'requirements-research.txt' }
& $researchPython -m pip install --disable-pip-version-check -r $requirementsPath
exit $LASTEXITCODE
