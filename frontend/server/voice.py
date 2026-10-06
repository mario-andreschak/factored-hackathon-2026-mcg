"""Speech in and out for the Savia assistant.

Voice is transport only. A recording becomes text that the browser sends
through the ordinary authenticated chat, and text the chat returned is read
aloud. Nothing here sees bank data, calls a bank tool or answers a question.

Providers are tried in order, so a self-hosted GPU endpoint can come first and
a hosted API can cover its cold start or an outage.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import struct
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

import httpx

logger = logging.getLogger("banking.voice")

OPENROUTER = "https://openrouter.ai/api/v1"
MAX_WAV_BYTES = 2 * 1024 * 1024
MAX_SECONDS = 30.1
MAX_TEXT = 1200
MAX_SPEECH_BYTES = 16 * 1024 * 1024
LANGUAGES = ("es", "pt")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class VoiceError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code, self.message = status_code, message


@dataclass(frozen=True)
class Provider:
    name: str
    kind: str  # "openai": multipart transcription; "openrouter": JSON transcription
    base_url: str
    api_key: str = field(repr=False)
    stt_model: str | None
    tts_model: str | None
    voices: dict[str, str]
    sample_rate: int
    timeout: float

    @classmethod
    def parse(cls, raw: dict) -> "Provider":
        if not isinstance(raw, dict):
            raise ValueError("Each voice provider must be an object")
        kind = raw.get("kind", "openai")
        if kind not in {"openai", "openrouter"}:
            raise ValueError("Voice provider kind must be openai or openrouter")
        base_url = str(raw.get("base_url") or (OPENROUTER if kind == "openrouter" else "")).rstrip("/")
        if not re.fullmatch(r"https?://[^\s?#]+", base_url):
            raise ValueError("Voice provider needs an http(s) base_url")
        api_key = raw.get("api_key") or os.environ.get(str(raw.get("api_key_env", "")), "")
        if not isinstance(api_key, str) or not api_key:
            raise ValueError("Voice provider needs api_key or api_key_env")
        voices = raw.get("voices", {})
        if not isinstance(voices, dict) or any(k not in LANGUAGES or not isinstance(v, str) for k, v in voices.items()):
            raise ValueError("Voice provider voices map es/pt to a voice name")
        sample_rate = raw.get("sample_rate", 24000)
        if not isinstance(sample_rate, int) or not 8000 <= sample_rate <= 48000:
            raise ValueError("Voice provider sample_rate must be 8000 to 48000")
        return cls(name=str(raw.get("name", kind)), kind=kind, base_url=base_url, api_key=api_key,
                   stt_model=raw.get("stt_model"), tts_model=raw.get("tts_model"), voices=voices,
                   sample_rate=sample_rate, timeout=float(raw.get("timeout", 45)))


def load_config(config: dict | None) -> dict:
    """The banking config's `voice` object, or a separate private file."""
    if filename := os.environ.get("SAVIA_VOICE_CONFIG_FILE"):
        loaded = json.loads(Path(filename).read_text(encoding="utf-8-sig"))
        if not isinstance(loaded, dict):
            raise ValueError("Voice configuration must be an object")
        return loaded
    return config or {}


def wav_bytes(audio: str) -> bytes:
    """Accept only a short mono 16-bit PCM WAV, as the browser records it."""
    invalid = VoiceError(422, "La grabación no es válida.")
    try:
        data = base64.b64decode(audio, validate=True)
    except (binascii.Error, ValueError):
        raise invalid from None
    if not 44 <= len(data) <= MAX_WAV_BYTES or data[:4] != b"RIFF" or data[8:12] != b"WAVE" \
            or struct.unpack_from("<I", data, 4)[0] + 8 != len(data):
        raise invalid
    fmt, audio_bytes, offset = None, 0, 12
    while offset + 8 <= len(data):
        name, size = data[offset:offset + 4], struct.unpack_from("<I", data, offset + 4)[0]
        offset += 8
        if offset + size > len(data):
            raise invalid
        if name == b"fmt ":
            if size < 16 or fmt:
                raise invalid
            fmt = struct.unpack_from("<HHIIHH", data, offset)
        elif name == b"data":
            audio_bytes += size
        offset += size + size % 2
    if offset != len(data) or not fmt:
        raise invalid
    codec, channels, rate, per_second, alignment, bits = fmt
    if (codec, channels, bits, alignment) != (1, 1, 16, 2) or not 8000 <= rate <= 48000 \
            or per_second != rate * 2 or not audio_bytes or audio_bytes % 2 \
            or audio_bytes / per_second > MAX_SECONDS:
        raise invalid
    return data


class VoiceService:
    def __init__(self, config: dict | None, *, transport: httpx.AsyncBaseTransport | None = None,
                 clock=time.monotonic):
        raw = (config or {}).get("providers", [])
        if not isinstance(raw, list) or len(raw) > 4:
            raise ValueError("Voice providers must be a list of at most four entries")
        self.providers = [Provider.parse(item) for item in raw]
        # Live recognition asks about once a second while the customer speaks.
        self.rate_limit = int((config or {}).get("requests_per_minute", 120))
        self._transport, self._clock = transport, clock
        self._client: httpx.AsyncClient | None = None
        self._recent: dict[str, deque] = {}
        self._warmed = float("-inf")

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(transport=self._transport, follow_redirects=False)
        return self._client

    async def close(self):
        if self._client is not None:
            await self._client.aclose()

    def status(self) -> dict:
        return {"available": any(p.stt_model for p in self.providers) and any(p.tts_model for p in self.providers)}

    async def warm(self):
        """Start a sleeping self-hosted GPU while the customer opens the assistant."""
        now = self._clock()
        if now - self._warmed < 300:
            return
        self._warmed = now
        for provider in (p for p in self.providers if p.kind == "openai"):
            try:
                await self.client.get(f"{provider.base_url}/models", timeout=120,
                                      headers={"Authorization": f"Bearer {provider.api_key}"})
            except httpx.HTTPError as exc:
                logger.warning("Voice warm-up of %s failed: %s", provider.name, type(exc).__name__)

    def admit(self, session_id: str):
        now, window = self._clock(), self._recent.setdefault(session_id, deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.rate_limit:
            raise VoiceError(429, "Demasiadas solicitudes de voz. Espera un momento.")
        window.append(now)
        if len(self._recent) > 512:
            for key in [k for k, v in self._recent.items() if not v or now - v[-1] > 60]:
                del self._recent[key]

    async def transcribe(self, audio: str, language: str) -> str:
        data = wav_bytes(audio)
        for provider in (p for p in self.providers if p.stt_model):
            headers = {"Authorization": f"Bearer {provider.api_key}"}
            try:
                if provider.kind == "openrouter":
                    response = await self.client.post(
                        f"{provider.base_url}/audio/transcriptions", headers=headers, timeout=provider.timeout,
                        json={"model": provider.stt_model, "input_audio": {"data": audio, "format": "wav"},
                              "response_format": "json", "temperature": 0, "language": language})
                else:
                    response = await self.client.post(
                        f"{provider.base_url}/audio/transcriptions", headers=headers, timeout=provider.timeout,
                        files={"file": ("speech.wav", data, "audio/wav")},
                        data={"model": provider.stt_model, "language": language,
                              "response_format": "json", "temperature": "0"})
                if response.status_code != 200:
                    raise httpx.HTTPError(f"status {response.status_code}")
                text = response.json().get("text")
                if not isinstance(text, str) or len(text) > 8000:
                    raise ValueError("invalid transcription")
                return _CONTROL.sub(" ", text).strip()[:2000]
            except (httpx.HTTPError, ValueError, AttributeError) as exc:
                logger.warning("Voice transcription via %s failed: %s", provider.name, type(exc).__name__)
        raise VoiceError(503, "El reconocimiento de voz no está disponible. Puedes escribir.")

    async def speak(self, text: str, language: str, *,
                    required_sample_rate: int | None = None) -> tuple[int, AsyncIterator[bytes]]:
        """Open the first provider that starts streaming; return its rate and raw s16le PCM."""
        text = _CONTROL.sub(" ", text).strip()
        if not text or len(text) > MAX_TEXT:
            raise VoiceError(422, "El texto para leer no es válido.")
        for provider in (p for p in self.providers if p.tts_model
                         and (required_sample_rate is None or p.sample_rate == required_sample_rate)):
            body = {"model": provider.tts_model, "input": text, "response_format": "pcm",
                    **({"voice": provider.voices[language]} if language in provider.voices else {})}
            request = self.client.build_request(
                "POST", f"{provider.base_url}/audio/speech", json=body, timeout=provider.timeout,
                headers={"Authorization": f"Bearer {provider.api_key}"})
            response = None
            try:
                response = await self.client.send(request, stream=True)
                if response.status_code != 200:
                    raise httpx.HTTPError(f"status {response.status_code}")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type and content_type not in {"audio/pcm", "audio/x-pcm", "audio/raw", "application/octet-stream"}:
                    raise ValueError("unsupported speech content type")
                chunks = response.aiter_bytes()
                first = await anext(chunks, b"")
                # Transport fragments do not align with a container or error prefix.
                while first and (len(first) < 4 or not first.lstrip()) and len(first) < 128:
                    extra = await anext(chunks, b"")
                    if not extra:
                        break
                    first += extra
                # A container or JSON body here would be played as raw PCM noise.
                if (not first or not first.lstrip()
                        or first[:4] in {b"RIFF", b"RIFX", b"RF64", b"OggS", b"fLaC", b"\x1a\x45\xdf\xa3"}
                        or first[:3] == b"ID3" or first.lstrip()[:1] in {b"{", b"["}):
                    raise ValueError("unsupported speech format")
            except (httpx.HTTPError, ValueError) as exc:
                if response is not None:
                    await response.aclose()
                logger.warning("Voice speech via %s failed: %s", provider.name, type(exc).__name__)
                continue

            async def stream(response=response, chunks=chunks, first=first, name=provider.name):
                sent = 0
                try:
                    chunk = first
                    while chunk:
                        sent += len(chunk)
                        if sent > MAX_SPEECH_BYTES:
                            raise VoiceError(503, "La voz no está disponible ahora. Puedes escribir.")
                        yield chunk
                        chunk = await anext(chunks, b"")
                except httpx.HTTPError as exc:
                    logger.warning("Voice speech via %s ended early: %s", name, type(exc).__name__)
                    raise VoiceError(503, "La voz no está disponible ahora. Puedes escribir.") from None
                finally:
                    await response.aclose()

            return provider.sample_rate, stream()
        raise VoiceError(503, "La voz no está disponible ahora. Puedes escribir.")
