$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:TEMP='D:\CodexWork\temp'
$env:TMP=$env:TEMP
$env:PIP_CACHE_DIR='D:\CodexWork\cache\pip'
$env:HF_HOME='D:\CodexWork\cache\intent-semantic-minilm'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
$learningPython=Join-Path $PSScriptRoot '.venv-research\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $learningPython)){throw '请先运行setup-research.ps1建立D盘研究环境'}
& $learningPython -B -m pip install --disable-pip-version-check -r requirements-learning.txt
if ($LASTEXITCODE -ne 0){throw '本地训练依赖安装失败'}
& $learningPython -B scripts/setup_semantic_encoder.py
if ($LASTEXITCODE -ne 0){throw '语义编码器下载或校验失败'}
