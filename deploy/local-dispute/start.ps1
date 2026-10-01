param(
  [Parameter(Mandatory=$true)][ValidatePattern('^.+@sha256:[a-f0-9]{64}$')][string]$Image,
  [string]$AuthFile = (Join-Path $env:USERPROFILE '.codex\auth.json'),
  [string]$OutputRoot = (Join-Path $env:USERPROFILE '.codex\local-dispute-demo\20261001'),
  [switch]$Start
)
$ErrorActionPreference = 'Stop'
$demoName = 'codex-dispute-local-20261001'
$volumeName = $demoName + '-data'
$ownerLabel = '01a0f97d-c4fa-7d51-bf5c-50edd8e7b1f4'
$sourceRevision = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $sourceRevision -notmatch '^[a-f0-9]{40}$') { throw 'Run from the committed demo worktree.' }
$resolvedAuthFile = (Resolve-Path -LiteralPath $AuthFile).Path
if (-not (Test-Path -LiteralPath $resolvedAuthFile -PathType Leaf)) { throw 'File-backed Codex login required.' }
$publicRoot = Join-Path ([IO.Path]::GetFullPath($OutputRoot)) ('source-' + $sourceRevision)
& node (Join-Path $PSScriptRoot 'export-source.mjs') $publicRoot $sourceRevision
if ($LASTEXITCODE -ne 0) { throw 'Public source export failed.' }
if (-not $Start) {
  Write-Output 'Public source prepared. Supply -Start only after the shared resource lease handoff.'
  return
}
$systemMemory = Get-CimInstance Win32_OperatingSystem
$physicalGiB = $systemMemory.FreePhysicalMemory / 1MB
$commitGiB = $systemMemory.FreeVirtualMemory / 1MB
if ($physicalGiB -lt 6 -or $commitGiB -lt 16) { throw 'Two-GiB demo admission requires 6GiB free physical and 16GiB available commit.' }
$volumeJson = & docker volume inspect $volumeName 2>$null
if ($LASTEXITCODE -ne 0) {
  & docker volume create --label "io.savia.local-demo.owner=$ownerLabel" $volumeName | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Dedicated volume creation failed.' }
} else {
  $volumeInfo = @($volumeJson | ConvertFrom-Json)[0]
  if ($volumeInfo.Labels.'io.savia.local-demo.owner' -ne $ownerLabel) { throw 'Existing volume has another owner.' }
}
$existing = & docker container inspect $demoName 2>$null
if ($LASTEXITCODE -eq 0) {
  $containerInfo = @($existing | ConvertFrom-Json)[0]
  if ($containerInfo.Config.Labels.'io.savia.local-demo.owner' -ne $ownerLabel) { throw 'Existing container has another owner.' }
  if ($containerInfo.State.Running) { throw 'Demo is already running. Inspect it rather than starting a duplicate.' }
  & docker container rm $demoName | Out-Null # Named owned stopped container only; volume is retained.
  if ($LASTEXITCODE -ne 0) { throw 'Owned stopped-container cleanup failed.' }
}
$runArguments = @('run', '-d', '--name', $demoName, '--label', "io.savia.local-demo.owner=$ownerLabel",
  '--label', "io.savia.local-demo.source=$sourceRevision", '--memory', '2g', '--memory-swap', '2g',
  '--cpus', '2', '--pids-limit', '512', '--security-opt', 'seccomp=unconfined',
  '--publish', '127.0.0.1:43900:8080', '--mount', "type=volume,source=$volumeName,target=/data",
  '--mount', "type=bind,source=$publicRoot,target=/local-demo-source,readonly",
  '--mount', "type=bind,source=$resolvedAuthFile,target=/run/local-input/auth.json,readonly",
  '--env', 'LOCAL_DISPUTE_ORIGIN=http://127.0.0.1:43900', '--entrypoint', 'tini', $Image,
  '--', 'node', '/local-demo-source/deploy/local-dispute/runtime.mjs')
$containerId = & docker @runArguments
if ($LASTEXITCODE -ne 0) { throw 'Local runtime launch failed.' }
Write-Output "Owned runtime started: $containerId"
Write-Output 'Candidate UI: http://127.0.0.1:43900 . Readiness and real native intake still need verification.'
