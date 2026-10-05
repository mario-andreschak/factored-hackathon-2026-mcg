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
    app = create_app(configured, voice_transport=transport)
    with TestClient(app) as client:
        assert client.post("/api/voice/transcribe", json={"audio": wav()}, headers=ORIGIN).status_code == 401
        assert client.post("/api/voice/speak", json={"text": "Hola"}, headers=ORIGIN).status_code == 401
        assert not seen
        login = client.post("/api/auth/login", json={"profile": "colombia", "code": settings.demo_code}, headers=ORIGIN)
        assert login.status_code == 200
        # The fixture has no chat worker, so the portal does not offer voice.
        assert "voice" not in client.get("/api/chat/status").json()
        heard = client.post("/api/voice/transcribe", json={"audio": wav(), "language": "es"}, headers=ORIGIN)
        assert heard.status_code == 200 and heard.json() == {"text": "No reconozco este cargo."}
        current = app.state.bank_state.session(client.cookies.get("flujo_bank_session"))
        app.state.conversation.remember_result(current.id, "Tu caso fue recibido.")
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


def sse(*deltas):
    lines = [json.dumps({"choices": [{"index": 0, "delta": delta}]}) for delta in deltas]
    return "".join(f"data: {line}\n\n" for line in [*lines, "[DONE]"])


def audio_model(script):
    """A scripted native audio model beside the scripted speech providers."""
    seen = []

    def handler(request: httpx.Request):
        if request.url.path.endswith("/chat/completions"):
            seen.append(json.loads(request.content))
            return httpx.Response(200, text=script(seen[-1]), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"text": "¿Cuánto tengo en ahorros?"})

    return httpx.MockTransport(handler), seen


PCM = base64.b64encode(b"\x10\x00" * 300).decode()
ASKS = sse({"audio": {"transcript": "Claro, "}}, {"audio": {"data": PCM}}, {"audio": {"transcript": "lo reviso."}},
           {"tool_calls": [{"index": 0, "function": {"name": "consultar_savia", "arguments": '{"solicitud": "Quiero '}}]},
           {"tool_calls": [{"index": 0, "function": {"arguments": 'saber mi saldo de ahorros."}'}}]})
TELLS = sse({"audio": {"transcript": "Tienes 1.250.000 pesos."}}, {"audio": {"data": PCM}})


def test_the_voice_answers_itself_and_hands_bank_requests_to_savia():
    async def run():
        from frontend.server.conversation import Conversation
        transport, seen = audio_model(lambda body: TELLS if body["tool_choice"] == "none" else ASKS)
        voice = VoiceService({"providers": [GPU, ROUTER]}, transport=transport)
        talk = Conversation({}, voice, transport=transport)
        first = [e async for e in await talk.turn("s", "es", audio=wav(), fresh=True)]
        talk.played("s", first[-1]["turn_id"], first[-1]["samples"], True)
        talk.remember_result("s", "Saldo de ahorros: **$1.250.000 COP**.")
        told = [e async for e in await talk.turn("s", "es", result="Saldo de ahorros: **$1.250.000 COP**.")]
        talk.played("s", told[-1]["turn_id"], told[-1]["samples"], True)
        busy = [e async for e in await talk.turn("s", "es", audio=wav(), working=True)]
        await talk.close(), await voice.close()
        return talk, first, told, busy, seen

    talk, first, told, busy, seen = asyncio.run(run())
    assert talk.status() == {"conversation": True, "persona": "moss"}
    kinds = [e["type"] for e in first]
    assert kinds[0] == "start" and kinds[-3:] == ["delegate", "heard", "complete"]
    assert next(e for e in first if e["type"] == "heard")["text"] == "¿Cuánto tengo en ahorros?"
    assert first[-3]["request"] == "Quiero saber mi saldo de ahorros."
    assert first[-1]["text"] == "Claro, lo reviso."
    assert base64.b64decode(next(e for e in first if e["type"] == "audio")["data"]) == b"\x10\x00" * 300
    # The recording goes to the model as audio; Moss is the default, calm persona.
    assert seen[0]["model"] == "openai/gpt-audio" and seen[0]["audio"] == {"voice": "coral", "format": "pcm16"}
    assert seen[0]["messages"][-1]["content"][0]["type"] == "input_audio"
    assert "Moss" in seen[0]["messages"][0]["content"] and "tortuga" in seen[0]["messages"][0]["content"]
    # Savia's reply is retold without tools, after what was already said.
    assert seen[1]["tool_choice"] == "none" and "$1.250.000 COP" in seen[1]["messages"][-1]["content"]
    assert [m["role"] for m in seen[1]["messages"][1:-1]] == ["user", "user", "assistant"]
    assert seen[1]["messages"][3]["content"] == "Claro, lo reviso."
    assert "Quiero saber mi saldo" in seen[1]["messages"][2]["content"]
    assert [e["type"] for e in told] == ["start", "caption", "audio", "complete"]
    # While Savia works, the voice keeps talking but cannot send a second request.
    assert seen[2]["tool_choice"] == "none" and "todavía está trabajando" in seen[2]["messages"][0]["content"]
    assert len(seen[2]["messages"]) == 7 and "delegate" not in [e["type"] for e in busy]


def test_conversation_needs_a_key_and_can_be_turned_off():
    from frontend.server.conversation import Conversation
    assert Conversation({}, VoiceService({"providers": [GPU]})).status() == {}
    assert Conversation({"conversation": False}, VoiceService({"providers": [ROUTER]})).status() == {}
    spark = Conversation({"conversation": {"api_key": "k", "persona": "spark"}}, VoiceService({"providers": [GPU]}))
    assert spark.status() == {"conversation": True, "persona": "spark"}
    with pytest.raises(ValueError):
        Conversation({"conversation": {"api_key": "k", "persona": "hare"}}, VoiceService({}))
    with pytest.raises(VoiceError):
        asyncio.run(Conversation({}, VoiceService({})).turn("s", "es", message="Hola"))


def test_voice_turn_route_streams_events_for_a_session(settings):  # noqa: F811
    transport, _ = audio_model(lambda body: ASKS)
    configured = replace(settings, voice={"providers": [GPU, ROUTER]})
    with TestClient(create_app(configured, voice_transport=transport)) as client:
        assert client.post("/api/voice/turn", json={"audio": wav()}, headers=ORIGIN).status_code == 401
        client.post("/api/auth/login", json={"profile": "colombia", "code": settings.demo_code}, headers=ORIGIN)
        reply = client.post("/api/voice/turn", json={"audio": wav(), "fresh": True}, headers=ORIGIN)
        assert reply.status_code == 200 and reply.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in reply.text.splitlines()]
        assert events[0]["type"] == "start" and events[0]["sample_rate"] == 24000 and len(events[0]["turn_id"]) == 24 and events[-1]["type"] == "complete"
        assert {"type": "delegate", "request": "Quiero saber mi saldo de ahorros."} in events
        assert client.post("/api/voice/turn", json={"audio": wav(), "result": "x"}, headers=ORIGIN).status_code == 422
        assert client.post("/api/voice/turn", json={}, headers=ORIGIN).status_code == 422
        receipt = {"turn_id": events[-1]["turn_id"], "played_samples": events[-1]["samples"], "complete": True}
        assert client.post("/api/voice/played", json={**receipt, "played_samples": 1}, headers=ORIGIN).status_code == 409
        assert client.post("/api/voice/played", json={**receipt, "complete": "yes"}, headers=ORIGIN).status_code == 422
        assert client.post("/api/voice/played", json=receipt, headers=ORIGIN).status_code == 200
        assert client.post("/api/voice/played", json=receipt, headers=ORIGIN).status_code == 409
        client.cookies.clear()
        assert client.post("/api/voice/played", json=receipt, headers=ORIGIN).status_code == 401


def test_native_result_is_exact_current_session_once_and_replayed_host_read_cannot_reissue_it():
    async def run():
        from frontend.server.conversation import Conversation
        transport, seen = audio_model(lambda body: TELLS)
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({}, voice, transport=transport)
        reply = "Saldo de ahorros: **$1.250.000 COP**."
        talk.remember_result("owner", reply)
        for session, text in [("foreign", reply), ("owner", "Tu disputa fue resuelta.")]:
            with pytest.raises(VoiceError) as rejected:
                await talk.turn(session, "es", result=text)
            assert rejected.value.status_code == 409
        assert not seen
        events = [e async for e in await talk.turn("owner", "es", result=reply)]
        talk.remember_result("owner", reply)
        with pytest.raises(VoiceError):
            await talk.turn("owner", "es", result=reply)
        with pytest.raises(VoiceError):
            talk.played("foreign", events[-1]["turn_id"], events[-1]["samples"], True)
        assert len(seen) == 1
        await talk.close(), await voice.close()
    asyncio.run(run())


def test_generated_or_interrupted_reply_is_not_spoken_history_and_stale_ack_is_rejected():
    async def run():
        from frontend.server.conversation import Conversation
        transport, seen = audio_model(lambda body: TELLS)
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({}, voice, transport=transport)
        first = [e async for e in await talk.turn("s", "es", message="Hola")]
        second = [e async for e in await talk.turn("s", "es", message="Sigo aquí")]
        assert not any(m["role"] == "assistant" for m in seen[1]["messages"])
        with pytest.raises(VoiceError):
            talk.played("s", first[-1]["turn_id"], first[-1]["samples"], True)
        talk.played("s", second[-1]["turn_id"], second[-1]["samples"], True)
        events = await talk.turn("s", "es", message="No he terminado")
        await anext(events), await anext(events)
        await events.aclose()
        fourth = [e async for e in await talk.turn("s", "es", message="Ahora sí")]
        assert sum(m["role"] == "assistant" for m in seen[3]["messages"]) == 1
        talk.forget("s")
        with pytest.raises(VoiceError):
            talk.played("s", fourth[-1]["turn_id"], fourth[-1]["samples"], True)
        await talk.close(), await voice.close()
    asyncio.run(run())


def test_truncated_or_odd_pcm_native_stream_never_gains_a_complete_receipt():
    async def run(script):
        from frontend.server.conversation import Conversation
        transport, _ = audio_model(lambda body: script)
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({}, voice, transport=transport)
        events = [e async for e in await talk.turn("s", "es", message="Hola")]
        assert events[-1]["type"] == "error" and "s" not in talk._pending
        await talk.close(), await voice.close()
    asyncio.run(run(TELLS.replace("data: [DONE]\n\n", "")))
    asyncio.run(run(sse({"audio": {"data": base64.b64encode(b"x").decode()}})))


def test_dictation_narration_uses_only_current_host_chunks_once():
    from frontend.server.conversation import Conversation
    talk = Conversation({"conversation": False}, VoiceService({}))
    reply = "**Tu consulta** sigue en revisión; no se ha movido dinero."
    spoken = "Tu consulta sigue en revisión; no se ha movido dinero."
    talk.remember_result("s", reply)
    with pytest.raises(VoiceError):
        talk.consume_speech("foreign", spoken)
    with pytest.raises(VoiceError):
        talk.consume_speech("s", "Tu disputa fue resuelta.")
    talk.consume_speech("s", spoken)
    talk.remember_result("s", reply)
    with pytest.raises(VoiceError):
        talk.consume_speech("s", spoken)
