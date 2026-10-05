param(
    [Parameter(Mandatory = $true)][string]$QualifiedArchive,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{64}$')][string]$QualifiedArchiveSha256
)
$ErrorActionPreference = 'Stop'
$taskBaseImage = 'flujo-slack-worker:turn-provenance-20260930'
$taskExpectedBase = 'sha256:a071761b46eed021471508f8de8b7d5726752125a3d19e66c4b286d59bde6d86'
$taskObservedBase = (& docker image inspect $taskBaseImage --format '{{.Id}}').Trim()
if ($LASTEXITCODE -ne 0 -or $taskObservedBase -ne $taskExpectedBase) {
    throw 'Original local worker image does not match the approved base.'
}
$taskArchive = (Resolve-Path -LiteralPath $QualifiedArchive).Path
if ((Get-FileHash -LiteralPath $taskArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $QualifiedArchiveSha256) {
    throw 'Qualified archive does not match the approved digest.'
}
$taskWorkerMetadata = (& docker inspect flujo-slack-flujo-1 | ConvertFrom-Json)[0]
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the existing local worker.' }
$taskLabels = $taskWorkerMetadata.Config.Labels
$taskProjectDirectory = $taskLabels.'com.docker.compose.project.working_dir'
$taskProjectName = $taskLabels.'com.docker.compose.project'
$taskFiles = $taskLabels.'com.docker.compose.project.config_files'
if (-not $taskProjectDirectory -or -not $taskProjectName -or -not $taskFiles) {
    throw 'Existing worker has no complete Compose provenance.'
}
$taskOverride = Join-Path $PSScriptRoot 'compose.override.yaml'
$taskComposeArguments = @('compose', '--project-name', $taskProjectName)
foreach ($taskFile in $taskFiles.Split(',')) {
    if ((Resolve-Path -LiteralPath $taskFile).Path -ne $taskOverride) {
        $taskComposeArguments += @('-f', $taskFile)
    }
}
$taskComposeArguments += @('-f', $taskOverride)
$taskPreviousWorkerImage = $env:FLUJO_WORKER_IMAGE
$taskInitializationImage = $taskPreviousWorkerImage
if (-not $taskInitializationImage) {
    $taskInitializationImage = (& docker inspect "$taskProjectName-init-1" --format '{{.Config.Image}}').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $taskInitializationImage) {
        throw 'Could not recover the existing Compose initialization image.'
    }
}
$taskArtifacts = Join-Path $PSScriptRoot '.artifacts'
New-Item -ItemType Directory -Path $taskArtifacts -Force | Out-Null
Copy-Item -LiteralPath $taskArchive -Destination (Join-Path $taskArtifacts 'next.tar') -Force
& docker build --pull=false --build-arg "QUALIFIED_NEXT_SHA256=$QualifiedArchiveSha256" -t flujo-slack-worker:banking-auth-20260930 $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Qualified local image build failed; existing services have not been changed.' }
Push-Location -LiteralPath $taskProjectDirectory
try {
    # This original Compose variable was supplied by the previous deployment's
    # shell. Recover it from the existing init service; do not recreate init.
    $env:FLUJO_WORKER_IMAGE = $taskInitializationImage
    # The gateway shares this worker's network namespace. Recreate both together,
    # using the existing images and every existing Compose overlay and volume.
    & docker @taskComposeArguments up -d --no-build --no-deps --force-recreate --wait --wait-timeout 180 flujo gateway
    if ($LASTEXITCODE -ne 0) { throw 'Local worker update failed; inspect the existing Compose services.' }
} finally {
    $env:FLUJO_WORKER_IMAGE = $taskPreviousWorkerImage
    Pop-Location
}
