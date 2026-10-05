$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$out = Join-Path $repo 'docs\submission\media\decks'
$app = New-Object -ComObject PowerPoint.Application
$app.Visible = $true
$app.WindowState = 2

try {
    foreach ($name in @('savia-submission-deck', 'savia-pitch-deck')) {
        $path = Join-Path $out ($name + '.pptx')
        $notesPath = Join-Path $out ($name + '-speaker-notes.json')
        $notes = @(Get-Content $notesPath -Raw | ConvertFrom-Json)
        $presentation = $app.Presentations.Open($path, $false, $false, $false)
        for ($i = 1; $i -le $presentation.Slides.Count; $i++) {
            $presentation.Slides.Item($i).NotesPage.Shapes.Placeholders.Item(2).TextFrame.TextRange.Text = [string]$notes[$i - 1]
        }
        $presentation.Save()
        $presentation.SaveAs((Join-Path $out ($name + '.pdf')), 32)
        $slides = Join-Path $out ($name + '-slides')
        New-Item -ItemType Directory -Force $slides | Out-Null
        for ($i = 1; $i -le $presentation.Slides.Count; $i++) {
            $png = Join-Path $slides ('slide-{0:D2}.png' -f $i)
            $presentation.Slides.Item($i).Export($png, 'PNG', 1600, 900)
        }
        $presentation.Close()
    }
}
finally {
    $app.Quit()
    [void][System.Runtime.Interopservices.Marshal]::ReleaseComObject($app)
}
