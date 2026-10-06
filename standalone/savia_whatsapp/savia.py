"""Authenticated HTTP client for a separate fictional Savia RC instance.

WhatsApp delivery does not establish audio playback. Every completed native
turn is cancelled with a false playback receipt; generated speech therefore
never becomes Savia's heard assistant history through this adapter.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass
import io
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import wave

import httpx

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_SAMPLES = 1_440_000
TURN_ID = re.compile(r"^[A-Za-z0-9_-]{24}$")


class SaviaError(RuntimeError):
    """Bounded diagnostics that never include credentials or customer content."""


@dataclass(frozen=True, slots=True)
class VoiceTurn:
    turn_id: str
    caption: str
    wav: bytes
    sample_rate: int
    samples: int


@dataclass(frozen=True, slots=True)
class SaviaReply:
    text: str
    voice_turns: tuple[VoiceTurn, ...]
    heard_text: str = ""
    delegated_request: str | None = None


def _validate_input_wav(data: bytes) -> None:
    if not isinstance(data, bytes) or not 44 <= len(data) <= MAX_INPUT_BYTES:
        raise SaviaError("Voice input must be a short mono PCM16 WAV")
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE" or int.from_bytes(data[4:8], "little") + 8 != len(data):
        raise SaviaError("Voice input must be a complete WAV")
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            if (audio.getnchannels(), audio.getsampwidth(), audio.getcomptype()) != (1, 2, "NONE") \
                    or not 8000 <= rate <= 48000 or not 0 < frames / rate <= 30.1 \
                    or len(audio.readframes(frames)) != frames * 2:
                raise SaviaError("Voice input must be at most 30.1 seconds of mono PCM16")
    except (wave.Error, EOFError):
        raise SaviaError("Voice input is not a valid PCM16 WAV") from None


def _wav(pcm: bytes, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm)
    return buffer.getvalue()


class SaviaClient:
    def __init__(self, base_url: str, fixture_file: str | Path, profile: str = "mexico",
                 language: str = "es", *, timeout: float = 480,
                 transport: httpx.AsyncBaseTransport | None = None):
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} \
                or parsed.port is None or not 1024 < parsed.port < 65536 \
                or parsed.username or parsed.password or parsed.path not in {"", "/"} \
                or parsed.query or parsed.fragment:
            raise SaviaError("Savia requires an exact loopback HTTP origin with a port")
        if profile not in {"mexico", "colombia", "argentina"} or language not in {"es", "pt"}:
            raise SaviaError("Choose a supported fictional profile and language")
        self.base_url = base_url.rstrip("/")
        self.fixture_file = Path(fixture_file).expanduser().resolve()
        self.profile, self.language = profile, language
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout,
                                      headers={"Origin": self.base_url},
                                      follow_redirects=False, trust_env=False, transport=transport)
        self._logged_in = False
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def close(self):
        await self._http.aclose()

    def _admission(self) -> str:
        try:
            fixture = json.loads(self.fixture_file.read_text(encoding="utf-8-sig"))
            root = Path(fixture["root"]).resolve()
            source = Path(fixture["source"]).resolve()
            code = fixture["demo_code"]
            if root != self.fixture_file.parent or source.parent != root \
                    or not (source / "QUALIFICATION_SYNTHETIC.json").is_file() \
                    or self.profile not in fixture["profiles"] \
                    or not isinstance(code, str) or not 1 <= len(code) <= 128:
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            raise SaviaError("A fresh RC fictional fixture is required for login") from None
        return code

    @staticmethod
    def _status(response: httpx.Response, route: str) -> None:
        if response.status_code != 200:
            raise SaviaError(f"Savia {route} failed with HTTP {response.status_code}")

    async def _post(self, route: str, body: dict) -> httpx.Response:
        try:
            response = await self._http.post(route, json=body)
        except httpx.HTTPError:
            raise SaviaError(f"Savia {route} transport failed") from None
        self._status(response, route)
        return response

    async def login(self) -> None:
        response = await self._post("/api/auth/login", {"profile": self.profile, "code": self._admission()})
        try:
            value = response.json()
            valid = value.get("authenticated") is True and value.get("profile", {}).get("id") == self.profile
        except (ValueError, AttributeError):
            valid = False
        if not valid or not self._http.cookies.get("flujo_bank_session"):
            raise SaviaError("Savia login did not bind the selected fictional profile")
        self._logged_in = True

    async def _cancel(self, turn_id: str) -> None:
        await self._post("/api/voice/played", {"turn_id": turn_id, "played_samples": 0, "complete": False})

    async def _turn(self, body: dict) -> tuple[VoiceTurn, str, str | None]:
        route = "/api/voice/turn"
        pcm = bytearray()
        turn_id, sample_rate, caption, heard, delegated = None, None, "", "", None
        completed = None
        try:
            async with self._http.stream("POST", route, json={"language": self.language, **body}) as response:
                self._status(response, route)
                if response.headers.get("content-type", "").split(";")[0] != "application/x-ndjson":
                    raise SaviaError("Savia voice response has an unexpected content type")
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    if len(line) > 100_000 or completed is not None:
                        raise SaviaError("Savia voice response has invalid event ordering")
                    try:
                        event = json.loads(line)
                    except ValueError:
                        raise SaviaError("Savia voice response contains malformed JSON") from None
                    if not isinstance(event, dict):
                        raise SaviaError("Savia voice response contains an invalid event")
                    kind = event.get("type")
                    if kind == "start":
                        identifier = event.get("turn_id")
                        if turn_id is not None or not isinstance(identifier, str) or not TURN_ID.fullmatch(identifier) \
                                or type(event.get("sample_rate")) is not int or event["sample_rate"] != 24000:
                            raise SaviaError("Savia voice start does not match the RC audio contract")
                        turn_id, sample_rate = identifier, event["sample_rate"]
                    elif turn_id is None:
                        raise SaviaError("Savia voice response is missing its start event")
                    elif kind in {"caption", "heard"}:
                        text = event.get("text")
                        if not isinstance(text, str) or len(text) > (4000 if kind == "caption" else 2000):
                            raise SaviaError("Savia voice text exceeds the RC contract")
                        if kind == "caption":
                            caption = text
                        else:
                            heard = text
                    elif kind == "audio":
                        encoded = event.get("data")
                        try:
                            chunk = base64.b64decode(encoded, validate=True) if isinstance(encoded, str) else b""
                        except (ValueError, binascii.Error):
                            raise SaviaError("Savia voice response contains invalid PCM encoding") from None
                        if not chunk or len(chunk) % 2 or len(pcm) + len(chunk) > MAX_OUTPUT_SAMPLES * 2:
                            raise SaviaError("Savia voice response contains invalid or excessive PCM")
                        pcm.extend(chunk)
                    elif kind == "delegate":
                        request = event.get("request")
                        if delegated is not None or not isinstance(request, str) or not 0 < len(request) <= 2000 \
                                or request != (heard if "audio" in body else body.get("message")):
                            raise SaviaError("Savia delegation does not match the current customer utterance")
                        delegated = request
                    elif kind == "complete":
                        if event.get("turn_id") != turn_id or type(event.get("samples")) is not int \
                                or event["samples"] <= 0 or event["samples"] * 2 != len(pcm) \
                                or event.get("text") != caption:
                            raise SaviaError("Savia voice completion does not match received audio")
                        completed = event["samples"]
                    else:
                        raise SaviaError("Savia voice response failed or contains an unknown event")
        except httpx.HTTPError:
            raise SaviaError("Savia voice stream transport failed") from None
        if completed is None or turn_id is None or sample_rate is None:
            raise SaviaError("Savia voice stream ended before a complete reply")
        # Complete generation permits packaging, but is never a heard receipt.
        await self._cancel(turn_id)
        return VoiceTurn(turn_id, caption, _wav(bytes(pcm), sample_rate), sample_rate, completed), heard, delegated

    async def converse(self, message: str | None = None, audio_wav: bytes | None = None) -> SaviaReply:
        if (message is None) == (audio_wav is None):
            raise SaviaError("Provide exactly one text message or WAV recording")
        if message is not None and (not isinstance(message, str) or not message.strip() or len(message) > 2000):
            raise SaviaError("Text input must contain 1 to 2000 characters")
        if audio_wav is not None:
            _validate_input_wav(audio_wav)
        body = ({"message": message} if message is not None else
                {"audio": base64.b64encode(audio_wav).decode("ascii")})
        async with self._lock:
            if not self._logged_in:
                await self.login()
            first, heard, delegated = await self._turn(body)
            if delegated is None:
                return SaviaReply(first.caption, (first,), heard)
            response = await self._post("/api/chat/messages", {"message": delegated, "language": self.language})
            try:
                reply = response.json().get("reply")
            except (ValueError, AttributeError):
                reply = None
            if not isinstance(reply, str) or not 0 < len(reply) <= 4000:
                raise SaviaError("Savia chat did not return a bounded verified reply")
            # This exact response was registered by the authenticated host route.
            narration, _, repeated_delegate = await self._turn({"result": reply})
            if repeated_delegate is not None:
                raise SaviaError("Verified narration cannot delegate another bank request")
            return SaviaReply(reply, (first, narration), heard, delegated)
