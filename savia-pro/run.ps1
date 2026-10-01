# Savia Pro on Windows (PowerShell 5.1 or 7+).
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$python = (Get-Command python, python3, py -ErrorAction SilentlyContinue | Select-Object -First 1)
if (-not $python) { throw 'Python 3.11+ was not found on PATH.' }

Write-Host "`n1/4  Python dependencies" -ForegroundColor Cyan
& $python.Source -m pip install --quiet --disable-pip-version-check -r requirements.txt

Write-Host "`n2/4  Serving database" -ForegroundColor Cyan
if (-not (Test-Path 'var/serving.duckdb') -or ($args -contains '--rebuild')) {
    & $python.Source 'tools/build_serving.py' '--verify'
} else {
    Write-Host '     var/serving.duckdb already present (use --rebuild to refresh)'
}

Write-Host "`n3/4  Web client" -ForegroundColor Cyan
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location web
    if (-not (Test-Path 'node_modules')) { npm install --no-audit --no-fund }
    npm run build
    Pop-Location
} else {
    Write-Host '     npm not found - the API will serve without a bundled client.'
}

$port = if ($env:SAVIA_PORT) { $env:SAVIA_PORT } else { '43950' }
Write-Host "`n4/4  Serving on http://127.0.0.1:$port/" -ForegroundColor Green
& $python.Source -m server.main --port $port
