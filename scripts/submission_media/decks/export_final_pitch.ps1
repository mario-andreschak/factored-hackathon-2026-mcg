$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$out = Join-Path $repo 'docs\submission\media\decks\final'
$powerPointWasRunning = [bool](Get-Process -Name POWERPNT -ErrorAction SilentlyContinue)
$app = New-Object -ComObject PowerPoint.Application
$presentation = $null
try {
    $presentation = $app.Presentations.Open((Join-Path $out 'savia-final-pitch.pptx'), $false, $false, $false)
    if ($presentation.Slides.Count -ne 6) { throw 'Final pitch must contain six slides.' }
    $presentation.SaveAs((Join-Path $out 'savia-final-pitch.pdf'), 32)
    $slides = Join-Path $out 'slides'
    New-Item -ItemType Directory -Force $slides | Out-Null
    for ($i = 1; $i -le 6; $i++) {
        $presentation.Slides.Item($i).Export((Join-Path $slides ('slide-{0:D2}.png' -f $i)), 'PNG', 1600, 900)
    }
}
finally {
    if ($null -ne $presentation) {
        $presentation.Close()
        [void][System.Runtime.Interopservices.Marshal]::ReleaseComObject($presentation)
    }
    # Open without a window and preserve an existing user's PowerPoint session.
    if (-not $powerPointWasRunning) { $app.Quit() }
    [void][System.Runtime.Interopservices.Marshal]::ReleaseComObject($app)
}
Write-Output 'Exported six PDF pages and six PNG slides.'
