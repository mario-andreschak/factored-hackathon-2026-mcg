$ErrorActionPreference = 'Stop'
$contextPath = 'C:/Users/Moe/.codex/tmp/savia-ui-runtime-c44d416fcf1a'
$configPath = 'C:/Users/Moe/.codex/tmp/savia-ui-successor-helper/build-only-c44d416fcf1a.fly.toml'
$pins = @{
    '.dockerignore' = 'f4775f01d127df7de9c632f8d566ac935c4e71858009b713a52a8f26b693ced9'
    'preparation-receipt.json' = 'c39f957f9efe7546369ea7f8c7972bf937e4bd151e43f9e3cff500a8b694e4dd'
    'Dockerfile' = '0411376ef09c732d8eeb150040561ea6c3159eb60d6d707105c0cf4c40f77ddb'
    'expected-ui-runtime.json' = '3d200c1f58957b3b3a032dbde642633e6c34eee70c7bee26734cdf0e1d137dd9'
    'verify_ui_layer.py' = 'be18516367db625156c97244419c21047f7de3c69885023ae30d562203f11d7c'
    'browser-build-provenance.json' = '666544efb1bf6afa6a4b0f053982fc70be2c776c1123fe237a17c2703bfd061e'
    'application/source-manifest.json' = '6ad47268b2d09dac11fdb74b9f73bff436b8aeed16ae183b15cf824f3828f806'
    'application/portal-source-manifest.json' = '652268ee73698b9f73219da6b2a5482bcfbab4efb02fcee7776f7ab9d16b57b7'
}
if ((Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'b7cc1c6925a2a1f526ffa7407b89f83c10d22ae9a866f80bbd35db8a81b426f3') {
    throw 'Exact build-only config hash mismatch'
}
foreach ($entry in $pins.GetEnumerator()) {
    $actual = (Get-FileHash -LiteralPath (Join-Path $contextPath $entry.Key) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.Value) { throw "Immutable build pin mismatch: $($entry.Key)" }
}
$expected = Get-Content -LiteralPath (Join-Path $contextPath 'expected-ui-runtime.json') -Raw | ConvertFrom-Json
if ($expected.final_head -ne 'c44d416fcf1ab95bcb16c77651418e6570d79782' -or $expected.final_tree -ne 'fabf02d622f51302e229137405e3607356d00ab0') {
    throw 'Exact source/tree pin mismatch'
}
foreach ($scope in @(@{Path='application'; Map=$expected.new_sources}, @{Path='browser-dist'; Map=$expected.new_browser})) {
    foreach ($entry in $scope.Map.PSObject.Properties) {
        $actual = (Get-FileHash -LiteralPath (Join-Path (Join-Path $contextPath $scope.Path) $entry.Name) -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $entry.Value) { throw "Immutable payload mismatch: $($entry.Name)" }
    }
}
$allowedFiles = @($pins.Keys) + @($expected.new_sources.PSObject.Properties | ForEach-Object { 'application/' + $_.Name }) + @($expected.new_browser.PSObject.Properties | ForEach-Object { 'browser-dist/' + $_.Name })
$actualFiles = @(Get-ChildItem -LiteralPath $contextPath -Recurse -Force -File | ForEach-Object { $_.FullName.Substring($contextPath.Length + 1).Replace('\','/') })
if (@(Compare-Object -ReferenceObject ($allowedFiles | Sort-Object -Unique) -DifferenceObject ($actualFiles | Sort-Object -Unique)).Count -ne 0) {
    throw 'Immutable context has missing or unexpected files'
}
if (@(Get-ChildItem -LiteralPath $contextPath -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count -ne 0) {
    throw 'Context contains a reparse point'
}
if ((Get-Content -LiteralPath $configPath -Raw) -notmatch '(?m)^app = "savia-rc-2026"$') { throw 'Build-only app config mismatch' }
$flyPath = (Get-Command fly -ErrorAction Stop).Source
$flyArguments = @('deploy', $contextPath, '--app', 'savia-rc-2026', '--config', $configPath,
    '--dockerfile', (Join-Path $contextPath 'Dockerfile'), '--ignorefile', (Join-Path $contextPath '.dockerignore'),
    '--build-only', '--remote-only', '--push', '--image-label', 'ui-ack-c44d416fcf1a', '--skip-release-command', '--yes')
# This is the only Fly operation. Keep --build-only present; promotion is a separate owner operation.
& $flyPath @flyArguments
if ($LASTEXITCODE -ne 0) { throw "Build-only Fly command failed with exit $LASTEXITCODE" }
