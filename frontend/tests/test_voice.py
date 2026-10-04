"""Voice endpoints against scripted providers; no audio leaves the test."""
from __future__ import annotations

import asyncio
import base64
import json
import struct
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from frontend.server.app import create_app
from frontend.server.voice import VoiceError, VoiceService, wav_bytes
from frontend.tests.test_api import settings  # noqa: F401  (shared snapshot fixture)

ORIGIN = {"Origin": "http://testserver"}


def wav(seconds=0.5, rate=16000, channels=1):
    pcm = b"\x01\x00" * int(seconds * rate) * channels
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack(
        "<IHHIIHH", 16, 1, channels, rate, rate * 2 * channels, 2 * channels, 16)
    return base64.b64encode(header + b"data" + struct.pack("<I", len(pcm)) + pcm).decode()


GPU = {"name": "gpu", "kind": "openai", "base_url": "https://gpu.test/v1", "api_key": "gpu-key",
       "stt_model": "whisper", "tts_model": "kokoro", "voices": {"es": "ef_dora", "pt": "pf_dora"}}
ROUTER = {"name": "router", "kind": "openrouter", "api_key": "router-key",
          "stt_model": "openai/whisper-large-v3", "tts_model": "google/gemini-3.8-flash-lite-tts", "voices": {"es": "Kore"}}


def providers(gpu_up=True):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        gpu = request.url.host == "gpu.test"
        if gpu and not gpu_up:
            return httpx.Response(503)
        if request.url.path.endswith("/audio/transcriptions"):
            return httpx.Response(200, json={"text": " No reconozco este cargo. " if gpu else "desde router"})
        return httpx.Response(200, content=b"\x10\x00" * 2400 if gpu else b"\x20\x00" * 100,
                              headers={"content-type": "audio/pcm"})

    return httpx.MockTransport(handler), seen


def test_wav_validation_rejects_anything_but_short_mono_pcm():
    assert wav_bytes(wav())[:4] == b"RIFF"
    for bad in (wav(channels=2), wav(seconds=31), base64.b64encode(b"RIFF" + b"\0" * 60).decode(), "@@@@"):
        with pytest.raises(VoiceError):
            wav_bytes(bad)


def test_gpu_provider_is_used_first_and_router_covers_its_outage():
    async def run(gpu_up):
        transport, seen = providers(gpu_up)
        service = VoiceService({"providers": [GPU, ROUTER]}, transport=transport)
        text = await service.transcribe(wav(), "es")
        rate, stream = await service.speak("Hola, soy Savia.", "es")
        audio = b"".join([chunk async for chunk in stream])
        await service.close()
        return text, rate, audio, seen

    text, rate, audio, seen = asyncio.run(run(True))
    assert (text, rate, len(audio)) == ("No reconozco este cargo.", 24000, 4800)
    assert [r.url.host for r in seen] == ["gpu.test", "gpu.test"]
    assert seen[0].headers["authorization"] == "Bearer gpu-key"
    assert b'name="language"\r\n\r\nes' in seen[0].content
    assert json.loads(seen[1].content) == {"model": "kokoro", "input": "Hola, soy Savia.",
                                           "response_format": "pcm", "voice": "ef_dora"}

    text, _, audio, seen = asyncio.run(run(False))
    assert (text, len(audio)) == ("desde router", 200)
    assert [r.url.host for r in seen] == ["gpu.test", "openrouter.ai", "gpu.test", "openrouter.ai"]
    assert json.loads(seen[1].content)["input_audio"]["format"] == "wav"


def test_all_providers_down_is_a_plain_unavailable_answer():
    async def run():
        transport, _ = providers(False)
        service = VoiceService({"providers": [GPU]}, transport=transport)
        with pytest.raises(VoiceError) as stt:
            await service.transcribe(wav(), "es")
        with pytest.raises(VoiceError) as tts:
            await service.speak("Hola", "es")
        return stt.value.status_code, tts.value.status_code

    assert asyncio.run(run()) == (503, 503)


def test_rate_limit_is_per_session():
    now = [0.0]
    service = VoiceService({"providers": [GPU], "requests_per_minute": 2}, clock=lambda: now[0])
    service.admit("a"), service.admit("a"), service.admit("b")
    with pytest.raises(VoiceError) as limited:
        service.admit("a")
    assert limited.value.status_code == 429
    now[0] = 61
    service.admit("a")


def test_voice_routes_require_a_session_and_stream_pcm(settings):  # noqa: F811
    transport, seen = providers()
    configured = replace(settings, voice={"providers": [GPU]})
    with TestClient(create_app(configured, voice_transport=transport)) as client:
        assert client.post("/api/voice/transcribe", json={"audio": wav()}, headers=ORIGIN).status_code == 401
        assert client.post("/api/voice/speak", json={"text": "Hola"}, headers=ORIGIN).status_code == 401
        assert not seen
        login = client.post("/api/auth/login", json={"profile": "colombia", "code": settings.demo_code}, headers=ORIGIN)
        assert login.status_code == 200
        # The fixture has no chat worker, so the portal does not offer voice.
        assert "voice" not in client.get("/api/chat/status").json()
        heard = client.post("/api/voice/transcribe", json={"audio": wav(), "language": "es"}, headers=ORIGIN)
        assert heard.status_code == 200 and heard.json() == {"text": "No reconozco este cargo."}
        spoken = client.post("/api/voice/speak", json={"text": "Tu caso fue recibido.", "language": "es"}, headers=ORIGIN)
        assert spoken.status_code == 200 and len(spoken.content) == 4800
        assert spoken.headers["x-audio-sample-rate"] == "24000"
        assert spoken.headers["content-type"].startswith("audio/pcm")
        assert client.post("/api/voice/speak", json={"text": "x" * 1201}, headers=ORIGIN).status_code == 422
        assert client.post("/api/voice/transcribe", json={"audio": wav(channels=2)}, headers=ORIGIN).status_code == 422


def test_unconfigured_voice_answers_unavailable(settings):  # noqa: F811
    with TestClient(create_app(settings)) as client:
        client.post("/api/auth/login", json={"profile": "colombia", "code": settings.demo_code}, headers=ORIGIN)
        assert client.post("/api/voice/speak", json={"text": "Hola"}, headers=ORIGIN).status_code == 503
