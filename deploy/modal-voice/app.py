"""Savia's own speech models on one on-demand Modal GPU.

Whisper large-v3 hears Spanish and Portuguese; Kokoro reads Savia's reply.
Both sit behind the two OpenAI-shaped routes the portal's voice service calls:

    POST /v1/audio/transcriptions   multipart: file (WAV), language
    POST /v1/audio/speech           JSON: input, voice, response_format "pcm"

Speech is streamed as raw 24 kHz mono s16le. Access is the bearer token in the
`savia-voice-auth` Modal secret. Recordings and text are neither stored nor
logged. The GPU starts on the first request and stops after ten idle minutes.
"""
import modal

APP = "savia-voice"
GPU = "T4"
STT_MODEL = "openai/whisper-large-v3"
TTS_REPO = "hexgrad/Kokoro-82M"
SAMPLE_RATE = 24000
# Kokoro names a voice by language and gender: e = Spanish, p = Brazilian Portuguese.
VOICES = {"e": "ef_dora", "p": "pf_dora"}
LANGUAGES = {"es": "spanish", "pt": "portuguese"}

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("espeak-ng")
    .pip_install("torch", "transformers", "accelerate", "kokoro>=0.9.4", "numpy",
                 "fastapi", "python-multipart", "huggingface-hub")
    .env({"HF_HOME": "/cache/huggingface", "HF_HUB_DISABLE_TELEMETRY": "1"})
)
app = modal.App(APP)
cache = modal.Volume.from_name(APP + "-model-cache", create_if_missing=True)
auth = modal.Secret.from_name(APP + "-auth", required_keys=["SAVIA_VOICE_TOKEN"])


@app.function(image=image, gpu=GPU, cpu=4, memory=16384, secrets=[auth], volumes={"/cache": cache},
              scaledown_window=600, min_containers=0, max_containers=1, timeout=300)
@modal.concurrent(max_inputs=8)
@modal.asgi_app()
def voice():
    import hmac
    import io
    import logging
    import os
    import threading
    import wave

    import numpy as np
    import torch
    from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
    from fastapi.responses import StreamingResponse
    from kokoro import KPipeline
    from transformers import pipeline

    token = os.environ["SAVIA_VOICE_TOKEN"]
    if len(token) < 32:
        raise RuntimeError("VOICE_AUTH_NOT_CONFIGURED")
    for name in ("uvicorn.access", "transformers", "kokoro"):
        logging.getLogger(name).setLevel(logging.ERROR)

    asr = pipeline("automatic-speech-recognition", model=STT_MODEL, torch_dtype=torch.float16, device="cuda")
    readers = {code: KPipeline(lang_code=code, repo_id=TTS_REPO, device="cuda") for code in VOICES}
    for code, reader in readers.items():  # Fetch each voice now, not during a customer's first reply.
        for _ in reader("uno", voice=VOICES[code]):
            pass
    cache.commit()
    gpu = threading.Lock()  # One model call at a time on the single GPU.
    web = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def authorize(request: Request):
        sent = request.headers.get("authorization", "")
        if not hmac.compare_digest(sent.encode(), f"Bearer {token}".encode()):
            raise HTTPException(401, "unauthorized")

    @web.get("/health")
    def health():
        return {"status": "ok"}

    @web.get("/v1/models")
    def models(request: Request):
        authorize(request)
        return {"object": "list", "data": [{"id": "whisper-large-v3", "object": "model"},
                                           {"id": "kokoro", "object": "model", "voices": sorted(VOICES.values())}]}

    @web.post("/v1/audio/transcriptions")
    def transcriptions(request: Request, file: UploadFile = File(...), language: str = Form("es"),
                       model: str = Form("whisper-large-v3"), response_format: str = Form("json"),
                       temperature: str = Form("0")):
        authorize(request)
        if language not in LANGUAGES:
            raise HTTPException(422, "language must be es or pt")
        body = file.file.read(4 * 1024 * 1024 + 1)
        if len(body) > 4 * 1024 * 1024:
            raise HTTPException(413, "recording too large")
        try:
            with wave.open(io.BytesIO(body)) as recording:
                rate, frames = recording.getframerate(), recording.getnframes()
                if recording.getnchannels() != 1 or recording.getsampwidth() != 2 or not frames or frames / rate > 31:
                    raise ValueError
                samples = np.frombuffer(recording.readframes(frames), dtype="<i2").astype(np.float32) / 32768
        except (wave.Error, ValueError, EOFError):
            raise HTTPException(422, "send at most 30 seconds of mono 16-bit PCM WAV") from None
        if rate != 16000:
            target = np.arange(int(len(samples) * 16000 / rate)) * (rate / 16000)
            samples = np.interp(target, np.arange(len(samples)), samples).astype(np.float32)
        with gpu:
            result = asr({"raw": samples, "sampling_rate": 16000},
                         generate_kwargs={"language": LANGUAGES[language], "task": "transcribe"})
        return {"text": result["text"].strip()}

    @web.post("/v1/audio/speech")
    async def speech(request: Request):
        authorize(request)
        body = await request.json()
        text, voice_name = body.get("input"), body.get("voice") or VOICES["e"]
        if not isinstance(text, str) or not text.strip() or len(text) > 1200:
            raise HTTPException(422, "input must be 1 to 1200 characters")
        if body.get("response_format", "pcm") != "pcm":
            raise HTTPException(422, "only response_format pcm is served")
        if voice_name not in VOICES.values():
            raise HTTPException(422, "unknown voice")
        reader = readers[voice_name[0]]

        def pcm():
            with gpu:
                for _, _, audio in reader(text.strip(), voice=voice_name, speed=1.0):
                    samples = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
                    yield (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()

        return StreamingResponse(pcm(), media_type="audio/pcm", headers={
            "X-Audio-Sample-Rate": str(SAMPLE_RATE), "X-Audio-Channels": "1", "X-Audio-Format": "s16le"})

    return web
