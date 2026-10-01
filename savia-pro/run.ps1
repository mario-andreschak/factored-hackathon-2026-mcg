# Savia Pro on Windows (PowerShell 5.1 or 7+).
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Invoke-CheckedNative {
    param([string]$Program, [string[]]$CommandArgs)
    & $Program @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "$Program failed with exit code $LASTEXITCODE. Bootstrap stopped."
    }
}

$python = (Get-Command python, python3, py -ErrorAction SilentlyContinue | Select-Object -First 1)
if (-not $python) { throw 'Python 3.11+ was not found on PATH.' }
$serving = if ($env:SAVIA_SERVING) { $env:SAVIA_SERVING } else { 'var/serving.duckdb' }

Write-Host "`n1/4  Python dependencies" -ForegroundColor Cyan
Invoke-CheckedNative $python.Source @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '-r', 'requirements.txt')

Write-Host "`n2/4  Serving database" -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath $serving) -or ($args -contains '--rebuild')) {
    Invoke-CheckedNative $python.Source @('tools/build_serving.py', '--verify')
} else {
    Write-Host "     $serving already present (use --rebuild to refresh)"
}

Write-Host "`n3/4  Web client" -ForegroundColor Cyan
if ($args -contains '--api-only') {
    Write-Host '     Web build skipped (--api-only).'
} elseif ($npm = Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location web
    try {
        if (-not (Test-Path -LiteralPath 'node_modules')) {
            Invoke-CheckedNative $npm.Source @('ci', '--no-audit', '--no-fund')
        }
        Invoke-CheckedNative $npm.Source @('run', 'build')
    } finally {
        Pop-Location
    }
} else {
    Write-Host '     npm not found - the API will serve without a bundled client.'
}

$port = if ($env:SAVIA_PORT) { $env:SAVIA_PORT } else { '43950' }
Write-Host "`n4/4  Serving on http://127.0.0.1:$port/" -ForegroundColor Green
Invoke-CheckedNative $python.Source @('-m', 'server.main', '--port', $port)
