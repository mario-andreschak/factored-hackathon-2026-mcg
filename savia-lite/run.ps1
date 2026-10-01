# Start Savia Lite on http://127.0.0.1:43900 (Windows PowerShell 5.1 or 7+).
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$python = $null
foreach ($name in 'python', 'python3', 'py') {
    $found = Get-Command $name -ErrorAction SilentlyContinue
    if ($found) { $python = $found; break }
}
if (-not $python) {
    throw 'Python 3 was not found on PATH. Install Python 3, or open index.html directly in a browser.'
}

Write-Host "Using $($python.Source)" -ForegroundColor DarkGray
& $python.Source 'serve.py' @args
