# Local synthetic INPUT only. No microphone, cloud provider, or model inference.
# Run from the canonical experiments folder; output is fixed ignored storage.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$fixtureRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../.local/personaplex-adaptive-prompt/fixtures'))
if (Test-Path -LiteralPath $fixtureRoot) { throw 'The fixed synthetic fixture directory already exists; do not overwrite it.' }
$null = New-Item -ItemType Directory -Path $fixtureRoot
$synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $voice = $synth.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'en-US' } | Select-Object -First 1
    if ($null -eq $voice) { throw 'An installed local en-US speech voice is required.' }
    $synth.SelectVoice($voice.VoiceInfo.Name)
    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $fixtures = @(
        @{ id = 'anxious'; rate = -1; text = 'I feel overwhelmed and need to slow down. Who are you, and can you help me take one small step?' },
        @{ id = 'planning'; rate = 0; text = 'I want to plan tomorrow clearly. Who are you, and can we make a simple three step plan?' },
        @{ id = 'energetic'; rate = 2; text = 'I am ready to go! Who are you? Let us do something fun and get moving.' },
        @{ id = 'slow-again'; rate = -1; text = 'Wait, I feel overwhelmed. Who are you now? Please slow down and help me breathe.' }
    )
    $records = @()
    foreach ($fixture in $fixtures) {
        $fixturePath = Join-Path $fixtureRoot ($fixture.id + '.wav')
        $synth.Rate = $fixture.rate
        $synth.SetOutputToWaveFile($fixturePath, $format)
        $synth.Speak($fixture.text)
        $synth.SetOutputToNull()
        $hashEngine = [System.Security.Cryptography.SHA256]::Create()
        try {
            $hash = [System.BitConverter]::ToString($hashEngine.ComputeHash([System.IO.File]::ReadAllBytes($fixturePath))).Replace('-', '').ToLowerInvariant()
        } finally { $hashEngine.Dispose() }
        $records += @{ id = $fixture.id; text = $fixture.text; rate = $fixture.rate; sha256 = $hash }
    }
    $manifest = @{ experiment = 'initial_adaptive_roles_native_v1'; generator = 'System.Speech local en-US'; microphone_used = $false; provider_used = $false; voice = $voice.VoiceInfo.Name; culture = $voice.VoiceInfo.Culture.Name; fixtures = $records }
    [System.IO.File]::WriteAllText((Join-Path $fixtureRoot 'manifest.json'), ($manifest | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
    Write-Output '{"status":"local_synthetic_fixtures_prepared","microphoneUsed":false,"providerUsed":false}'
} finally {
    $synth.Dispose()
}
