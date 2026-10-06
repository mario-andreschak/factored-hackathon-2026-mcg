param(
    [Parameter(Mandatory=$true)][string]$ReadinessSha,
    [switch]$RootGo,
    [switch]$FrozenCohortComplete
)
$ErrorActionPreference = 'Stop'
if (-not $RootGo -or -not $FrozenCohortComplete) { throw 'Root reviewed GO and completed frozen reviews required' }
$helperRoot = '[private-local-path]'
$readinessPath = Join-Path $helperRoot 'readiness.json'
if ((Get-FileHash -LiteralPath $readinessPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ReadinessSha) { throw 'Exact reviewed readiness SHA differs' }
$ready = Get-Content -LiteralPath $readinessPath -Raw | ConvertFrom-Json
if ($ready.schema -ne 'savia-card-admission-release-readiness/v1' -or $ready.source -ne 'f2fa597a481a87b5301531cf180f8f61d1f3ba70' -or $ready.tree -ne '1638e0be90b1046bbada1972b6ace1ee62a8e4fa') { throw 'Final replacement source/tree differs' }
$contextPath = Join-Path $helperRoot 'contexts/f2fa597a481a/build'
$configPath = Join-Path $helperRoot 'build-only.fly.toml'
foreach ($entry in $ready.helper_files.PSObject.Properties) {
    $actual = (Get-FileHash -LiteralPath (Join-Path $helperRoot $entry.Name) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.Value) { throw "Reviewed helper changed: $($entry.Name)" }
}
foreach ($entry in $ready.build_files.PSObject.Properties) {
    $actual = (Get-FileHash -LiteralPath (Join-Path $contextPath $entry.Name) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.Value) { throw "Immutable build file changed: $($entry.Name)" }
}
$actualFiles = @(Get-ChildItem -LiteralPath $contextPath -Recurse -Force -File | ForEach-Object { $_.FullName.Substring($contextPath.Length + 1).Replace('\','/') })
if (@(Compare-Object -ReferenceObject @($ready.build_files.PSObject.Properties.Name | Sort-Object) -DifferenceObject @($actualFiles | Sort-Object)).Count -ne 0) { throw 'Build context inventory differs' }
if (@(Get-ChildItem -LiteralPath $contextPath -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count -ne 0) { throw 'Build context reparse point denied' }
if ((Get-Content -LiteralPath $configPath -Raw) -notmatch '(?m)^app = "savia-rc-2026"$') { throw 'Exact build-only app differs' }
$flyPath = (Get-Command fly -ErrorAction Stop).Source
$flyArguments = @('deploy', $contextPath, '--app', 'savia-rc-2026', '--config', $configPath,
    '--dockerfile', (Join-Path $contextPath 'Dockerfile'), '--ignorefile', (Join-Path $contextPath '.dockerignore'),
    '--build-only', '--remote-only', '--push', '--image-label', 'native-card-f2fa597a481a', '--skip-release-command', '--yes')
# Sole Fly command. --build-only stays present. Full-config image promotion is separate.
& $flyPath @flyArguments
if ($LASTEXITCODE -ne 0) { throw 'Build-only failed; retain private output and never retry automatically' }
