# Savia voice on an on-demand GPU

One Modal app, `savia-voice`, on a single T4 that starts on demand and stops
after ten idle minutes. Whisper large-v3 transcribes Spanish and Portuguese;
Kokoro-82M reads replies with a Spanish (`ef_dora`) or Brazilian Portuguese
(`pf_dora`) voice. It is separate from the Qwen inference endpoint.

```powershell
pip install modal            # and a logged-in Modal profile
$env:OPENROUTER_API_KEY = '...'   # optional: adds the hosted fallback
python deploy/modal-voice/deploy.py
python deploy/modal-voice/smoke.py --save $env:TEMP\savia-voice
```

`deploy.py` creates the `savia-voice-auth` secret once and writes
`~/.savia-voice/voice.json` (endpoint and token, outside Git). `smoke.py` speaks
one sentence per language through each provider and transcribes it back.

Measured on 4 October 2026 with a warm container: first audio after 0.3 to 1.0
seconds and a four-second sentence transcribed in about 1.5 seconds. The hosted
fallback took about 3 seconds to first audio. The first request after
deployment took 54 seconds while the models downloaded. The portal asks the GPU
to start when a signed-in customer's chat status is loaded, and uses the
fallback for turns that arrive before it is up.

Not checked: a real microphone in a noisy room, accent quality judged by a
native listener, and cost under sustained use.
