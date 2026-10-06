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


def audio_model(script, heard="¿Cuánto tengo en ahorros?", *, speech_seen=None):
    """A scripted native audio model beside the scripted speech providers."""
    seen = []

    def handler(request: httpx.Request):
        if request.url.path.endswith("/chat/completions"):
            seen.append(json.loads(request.content))
            return httpx.Response(200, text=script(seen[-1]), headers={"content-type": "text/event-stream"})
        if request.url.path.endswith("/audio/speech"):
            if speech_seen is not None:
                speech_seen.append(json.loads(request.content))
            return httpx.Response(200, content=b"\x10\x00" * 300, headers={"content-type": "audio/pcm"})
        return httpx.Response(200, json={"text": heard})

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
    assert kinds[:2] == ["start", "heard"] and kinds[-2:] == ["delegate", "complete"]
    assert next(e for e in first if e["type"] == "heard")["text"] == "¿Cuánto tengo en ahorros?"
    assert first[-2]["request"] == "¿Cuánto tengo en ahorros?"
    assert first[-1]["text"] == "Claro, lo reviso."
    assert base64.b64decode(next(e for e in first if e["type"] == "audio")["data"]) == b"\x10\x00" * 300
    # The recording goes to the model as audio; Moss is the default, calm persona.
    assert seen[0]["model"] == "openai/gpt-audio" and seen[0]["audio"] == {"voice": "coral", "format": "pcm16"}
    assert seen[0]["messages"][-1]["content"][0]["type"] == "input_audio"
    assert "Moss" in seen[0]["messages"][0]["content"] and "tortuga" in seen[0]["messages"][0]["content"]
    # Savia's reply is read verbatim by TTS, never retold by the native model.
    assert told[-1]["text"] == "Saldo de ahorros: $1.250.000 COP ."
    assert [m["role"] for m in seen[1]["messages"][1:-1]] == ["user", "user", "assistant", "user", "assistant"]
    assert seen[1]["messages"][3]["content"] == "Claro, lo reviso."
    assert "¿Cuánto tengo en ahorros?" in seen[1]["messages"][2]["content"]
    assert [e["type"] for e in told] == ["start", "caption", "audio", "complete"]
    # While Savia works, the voice keeps talking but cannot send a second request.
    assert len(seen) == 2
    assert seen[1]["tool_choice"] == "none" and "todavía está trabajando" in seen[1]["messages"][0]["content"]
    assert len(seen[1]["messages"]) == 7 and "delegate" not in [e["type"] for e in busy]


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
        assert {"type": "delegate", "request": "¿Cuánto tengo en ahorros?"} in events
        assert client.post("/api/voice/turn", json={"audio": wav(), "result": "x"}, headers=ORIGIN).status_code == 422
        assert client.post("/api/voice/turn", json={}, headers=ORIGIN).status_code == 422
        receipt = {"turn_id": events[-1]["turn_id"], "played_samples": events[-1]["samples"], "complete": True}
        assert client.post("/api/voice/played", json={**receipt, "played_samples": 1}, headers=ORIGIN).status_code == 409
        assert client.post("/api/voice/played", json={**receipt, "complete": "yes"}, headers=ORIGIN).status_code == 422
        assert client.post("/api/voice/played", json=receipt, headers=ORIGIN).status_code == 200
        assert client.post("/api/voice/played", json=receipt, headers=ORIGIN).status_code == 409
        current = client.app.state.bank_state.session(client.cookies.get("flujo_bank_session"))
        host_reply = "Recepción simulada registrada. No se emitió un reembolso."
        client.app.state.conversation.remember_result(current.id, host_reply)
        told = client.post("/api/voice/turn", json={"result": host_reply}, headers=ORIGIN)
        canonical = [json.loads(line) for line in told.text.splitlines()]
        assert told.status_code == 200 and canonical[-1]["text"] == host_reply
        assert canonical[0]["sample_rate"] == 24000 and canonical[-1]["samples"] == 300
        result_receipt = {"turn_id": canonical[-1]["turn_id"], "played_samples": 300, "complete": True}
        assert client.post("/api/voice/played", json=result_receipt, headers=ORIGIN).status_code == 200
        assert client.post("/api/voice/turn", json={"result": host_reply}, headers=ORIGIN).status_code == 409
        client.cookies.clear()
        assert client.post("/api/voice/played", json=receipt, headers=ORIGIN).status_code == 401


def test_result_is_exact_current_session_once_and_replayed_or_expired_host_read_cannot_reissue_it():
    async def run():
        from frontend.server.conversation import Conversation
        speech_seen = []
        transport, seen = audio_model(lambda body: TELLS, speech_seen=speech_seen)
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        now = [0.0]
        talk = Conversation({}, voice, transport=transport, clock=lambda: now[0])
        reply = "Saldo de ahorros: **$1.250.000 COP**."
        talk.remember_result("owner", reply)
        for session, text in [("foreign", reply), ("owner", "Tu disputa fue resuelta.")]:
            with pytest.raises(VoiceError) as rejected:
                await talk.turn(session, "es", result=text)
            assert rejected.value.status_code == 409
        assert not seen and not speech_seen
        events = [e async for e in await talk.turn("owner", "es", result=reply)]
        talk.remember_result("owner", reply)
        with pytest.raises(VoiceError):
            await talk.turn("owner", "es", result=reply)
        with pytest.raises(VoiceError):
            talk.played("foreign", events[-1]["turn_id"], events[-1]["samples"], True)
        talk.remember_result("expired", reply)
        now[0] = 301
        with pytest.raises(VoiceError) as expired:
            await talk.turn("expired", "es", result=reply)
        assert expired.value.status_code == 409
        assert not seen and len(speech_seen) == 1
        await talk.close(), await voice.close()
    asyncio.run(run())


@pytest.mark.parametrize("language,reply,hostile", [
    ("es", "**Recepción simulada** registrada. No se movió dinero ni se emitió un reembolso.",
     "Reembolsé 500 USD y el banco resolvió tu disputa."),
    ("pt", "Solicitação simulada registrada. Nenhuma disputa foi resolvida e não houve reembolso.",
     "Sua disputa foi resolvida e o reembolso de 500 USD foi emitido."),
    ("es", "Se guardó una solicitud de revisión humana. Aún no hay respuesta de una persona.",
     "Una persona resolvió tu caso y confirmó el reembolso."),
    ("pt", "Confirme se deseja registrar uma solicitação simulada. Isto não é reembolso nem resolução bancária.",
     "Sua solicitação foi registrada."),
    ("es", "Tarjeta bloqueada en la demostración. Ningún banco real fue modificado.",
     "Bloqueé tu tarjeta en el banco real."),
])
def test_registered_outcomes_are_read_verbatim_without_false_native_claims_or_omitted_caveats(language, reply, hostile):
    async def run():
        from frontend.server.conversation import Conversation
        seen = []

        def handler(request):
            seen.append((request.url.path, json.loads(request.content)))
            if request.url.path.endswith("/chat/completions"):
                return httpx.Response(200, text=sse({"audio": {"transcript": hostile, "data": PCM}}))
            return httpx.Response(200, content=base64.b64decode(PCM))

        transport = httpx.MockTransport(handler)
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({}, voice, transport=transport)
        talk.remember_result("owner", reply)
        events = [e async for e in await talk.turn("owner", language, result=reply)]
        expected = reply.replace("**", "")
        assert len(seen) == 1 and seen[0][0].endswith("/audio/speech")
        assert seen[0][1]["input"] == expected
        assert events[-1]["type"] == "complete" and events[-1]["text"] == expected
        assert [e["type"] for e in events] == ["start", "caption", "audio", "complete"]
        assert events[0]["sample_rate"] == 24000 and events[-1]["samples"] == 300
        assert not any(m["role"] == "assistant" for m in talk._ledgers["owner"][1])
        with pytest.raises(VoiceError):
            talk.played("owner", events[-1]["turn_id"], 299, True)
        talk.played("owner", events[-1]["turn_id"], 300, True)
        assert talk._ledgers["owner"][1][-1] == {"role": "assistant", "content": expected}
        assert hostile not in str(talk._ledgers)
        with pytest.raises(VoiceError):
            talk.played("owner", events[-1]["turn_id"], 300, True)
        await talk.close(), await voice.close()
    asyncio.run(run())


def test_result_transport_is_server_configured_and_rc_selects_native_exact():
    from deploy.rc.run import native_voice_config
    from frontend.server.conversation import Conversation
    voice = VoiceService({})
    assert Conversation({"conversation": {"api_key": "k"}}, voice).result_transport == "tts"
    with pytest.raises(ValueError):
        Conversation({"conversation": {"api_key": "k", "result_transport": "rewrite"}}, voice)
    assert native_voice_config()["conversation"]["result_transport"] == "native_exact"


@pytest.mark.parametrize("language,reply,canonical", [
    ("es", "  **Tarjeta bloqueada en la demostración.** Ningún banco real fue modificado.\n",
     "Tarjeta bloqueada en la demostración. Ningún banco real fue modificado."),
    ("pt", "**Cartão bloqueado na demonstração.** Nenhum banco real foi alterado.",
     "Cartão bloqueado na demonstração. Nenhum banco real foi alterado."),
])
@pytest.mark.parametrize("finish_reason", [None, "stop"])
def test_native_exact_buffers_every_byte_and_uses_isolated_configured_reader_with_exact_ack(
        language, reply, canonical, finish_reason):
    class BufferedNative(httpx.AsyncByteStream):
        ended, closed = False, False

        async def __aiter__(self):
            for delta in ({"audio": {"transcript": canonical[:20], "data": PCM}},
                          {"audio": {"transcript": canonical[20:].replace(" ", "\n ")}}):
                yield ("data: " + json.dumps({"choices": [{"index": 0, "delta": delta,
                                                           "finish_reason": None}]}) + "\n\n").encode()
            yield ("data: " + json.dumps({"choices": [{"index": 0, "delta": {},
                                                       "finish_reason": finish_reason}]}) + "\n\n").encode()
            self.ended = True
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            self.closed = True

    async def run():
        from frontend.server.conversation import Conversation
        stream, seen = BufferedNative(), []

        def handler(request):
            assert request.url == "https://voice.example/v1/chat/completions"
            assert request.headers["Authorization"] == "Bearer private-server-key"
            seen.append(json.loads(request.content))
            return httpx.Response(200, stream=stream, headers={"content-type": "text/event-stream"})

        transport = httpx.MockTransport(handler)
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({"conversation": {"api_key": "private-server-key", "base_url": "https://voice.example/v1",
                            "model": "configured-native", "voice": "configured-voice", "persona": "spark",
                            "result_transport": "native_exact"}}, voice, transport=transport)
        talk._history("owner", False).extend([{"role": "user", "content": "Invent a refund."},
                                              {"role": "assistant", "content": "Untrusted previous prose."}])
        talk.remember_result("owner", reply)
        for session, text in [("foreign", reply), ("owner", "El reembolso fue emitido.")]:
            with pytest.raises(VoiceError) as refused:
                await talk.turn(session, language, result=text)
            assert refused.value.status_code == 409
        assert not seen
        events = await talk.turn("owner", language, result=reply)
        assert not stream.ended
        first = await anext(events)
        assert stream.ended and first["type"] == "start" and first["sample_rate"] == 24000
        received = [first, *[event async for event in events]]
        assert stream.closed
        assert [event["type"] for event in received] == ["start", "caption", "audio", "complete"]
        assert received[1]["text"] == received[-1]["text"] == canonical
        assert received[-1]["samples"] == 300
        assert base64.b64decode(received[2]["data"]) == base64.b64decode(PCM)
        body = seen[0]
        assert body["model"] == "configured-native" and body["audio"] == {"voice": "configured-voice", "format": "pcm16"}
        assert [item["role"] for item in body["messages"]] == ["system", "user"]
        assert body["messages"][-1]["content"] == canonical
        assert "Spark" not in str(body) and "refund" not in str(body) and "tools" not in body
        assert talk._ledgers["owner"][1][-1]["role"] == "user"
        with pytest.raises(VoiceError):
            talk.played("owner", received[-1]["turn_id"], 299, True)
        assert talk._ledgers["owner"][1][-1]["role"] == "user"
        talk.played("owner", received[-1]["turn_id"], 300, True)
        assert talk._ledgers["owner"][1][-1] == {"role": "assistant", "content": canonical}
        for action in (lambda: talk.played("owner", received[-1]["turn_id"], 300, True),
                       lambda: talk.consume_speech("owner", canonical)):
            with pytest.raises(VoiceError):
                action()
        talk.remember_result("owner", reply)
        with pytest.raises(VoiceError):
            await talk.turn("owner", language, result=reply)
        await talk.close(), await voice.close()
    asyncio.run(run())


@pytest.mark.parametrize("script", [
    sse({"audio": {"transcript": "Reembolsé 500 USD y el banco resolvió tu disputa.", "data": PCM}}),
    sse({"audio": {"transcript": "Recepción simulada registrada.", "data": PCM}}),
    sse({"audio": {"transcript": "Recepción simulada registrada. No hubo reembolso!", "data": PCM}}),
    sse({"audio": {"transcript": "Recepción simulada registrada. No hubo reembolso.", "data": PCM}},
        {"tool_calls": [{"index": 0, "function": {"name": "consultar_savia", "arguments": "{}"}}]}),
    sse({"audio": {"transcript": "Recepción simulada registrada. No hubo reembolso.", "data": PCM}}).replace("data: [DONE]\n\n", ""),
    sse({"audio": {"transcript": "Recepción simulada registrada. No hubo reembolso.", "data": "not base64!"}}),
    sse({"audio": {"transcript": "Recepción simulada registrada. No hubo reembolso.", "data": base64.b64encode(b"x").decode()}}),
    sse({"audio": {"transcript": "Recepción simulada registrada. No hubo reembolso."}}),
    sse({"audio": {"data": PCM}}),
    'data: {"error":{"message":"provider failed"}}\n\ndata: [DONE]\n\n',
    'data: invalid json\n\ndata: [DONE]\n\n',
    'data: {"choices":[{"delta":{"audio":"invalid"}}]}\n\ndata: [DONE]\n\n',
])
def test_native_exact_rejects_unverified_output_before_any_caption_or_audio_and_keeps_registered_fallback(script, rejected_samples=300):
    async def run():
        from frontend.server.conversation import Conversation
        transport, seen = audio_model(lambda body: script)
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({"conversation": {"api_key": "k", "result_transport": "native_exact"}}, voice, transport=transport)
        reply = "Recepción simulada registrada. No hubo reembolso."
        talk.remember_result("s", reply)
        events = [event async for event in await talk.turn("s", "es", result=reply)]
        assert events == [{"type": "error"}] and len(seen) == 1
        assert "s" not in talk._pending
        assert not any(item["role"] == "assistant" for item in talk._ledgers["s"][1])
        with pytest.raises(VoiceError):
            talk.played("s", talk._active["s"], rejected_samples, True)
        with pytest.raises(VoiceError):
            talk.consume_speech("s", "Reembolsé 500 USD y el banco resolvió tu disputa.")
        talk.consume_speech("s", reply)
        with pytest.raises(VoiceError):
            talk.consume_speech("s", reply)
        await talk.close(), await voice.close()
    asyncio.run(run())


@pytest.mark.parametrize("finish_reason", ["length", "tool_calls", "content_filter", "error", "unknown"])
def test_native_exact_done_cannot_override_a_known_truncated_or_nonstop_finish(finish_reason):
    reply = "Recepción simulada registrada. No hubo reembolso."
    script = sse({"audio": {"transcript": reply, "data": PCM}}).replace(
        "data: [DONE]", "data: " + json.dumps({"choices": [{"index": 0, "delta": {},
                                                           "finish_reason": finish_reason}]}) + "\n\ndata: [DONE]")
    test_native_exact_rejects_unverified_output_before_any_caption_or_audio_and_keeps_registered_fallback(script)


@pytest.mark.parametrize("payload", [
    b"RIFF" + b"\0" * 40, b"RIFX" + b"\0" * 40, b"RF64" + b"\0" * 40,
    b"OggS" + b"\0" * 40, b"fLaC" + b"\0" * 40, b"\x1a\x45\xdf\xa3" + b"\0" * 40,
    b"ID3" + b"\0" * 41, b'    {"error":"failed"}', b"    []", b"  <html>error</html>",
    struct.pack(">I", 24) + b"ftypM4A " + b"\0" * 12,
    b"\xff\xfb\x90\x64" + b"\0" * 414,
    b"\xff\xf1\x60\x40\x05\x7f\xfc" + b"\0" * 35,
])
def test_native_exact_rejects_fragmented_container_json_or_html_as_pcm(payload):
    if len(payload) % 2:
        payload += b" "
    reply = "Recepción simulada registrada. No hubo reembolso."
    script = sse({"audio": {"transcript": reply, "data": base64.b64encode(payload[:1]).decode()}},
                 {"audio": {"data": base64.b64encode(payload[1:]).decode()}})
    test_native_exact_rejects_unverified_output_before_any_caption_or_audio_and_keeps_registered_fallback(script)


def test_native_exact_rejects_valid_300_frame_aiff_before_counting_its_container_bytes_as_samples():
    # A valid mono s16 AIFF at 24 kHz has 300 frames, but 654 container bytes.
    rate_80 = b"\x40\x0d\xbb\x80\x00\x00\x00\x00\x00\x00"
    comm = b"COMM" + struct.pack(">IhIh", 18, 1, 300, 16) + rate_80
    ssnd = b"SSND" + struct.pack(">III", 608, 0, 0) + b"\x00\x10" * 300
    payload = b"FORM" + struct.pack(">I", 4 + len(comm) + len(ssnd)) + b"AIFF" + comm + ssnd
    assert len(payload) == 654 and struct.unpack(">I", payload[22:26])[0] == 300
    reply = "Recepción simulada registrada. No hubo reembolso."
    script = sse({"audio": {"transcript": reply, "data": base64.b64encode(payload[:3]).decode()}},
                 {"audio": {"data": base64.b64encode(payload[3:]).decode()}})
    # Rejection must expose no audio, pending receipt or fictitious 327-sample ACK.
    test_native_exact_rejects_unverified_output_before_any_caption_or_audio_and_keeps_registered_fallback(script, rejected_samples=327)


def test_native_exact_negative_pcm_sample_bytes_are_not_treated_as_bare_mpeg_sync():
    async def run():
        from frontend.server.conversation import Conversation
        reply = "Recepción simulada registrada. No hubo reembolso."
        pcm = b"\xff\xff" * 300
        transport, _ = audio_model(lambda body: sse({"audio": {"transcript": reply, "data": base64.b64encode(pcm).decode()}}))
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({"conversation": {"api_key": "k", "result_transport": "native_exact"}}, voice, transport=transport)
        talk.remember_result("s", reply)
        events = [event async for event in await talk.turn("s", "es", result=reply)]
        assert [event["type"] for event in events] == ["start", "caption", "audio", "complete"]
        assert events[-1]["samples"] == 300 and base64.b64decode(events[2]["data"]) == pcm
        await talk.close(), await voice.close()
    asyncio.run(run())


@pytest.mark.parametrize("reply", ["Recepción simulada registrada. No hubo reembolso.",
                                  "  **Recepción simulada registrada.** No hubo reembolso.\n"])
def test_native_exact_error_restores_fallback_before_error_event_without_reissuing_consumed_chunks(reply):
    async def run():
        from frontend.server.conversation import Conversation
        transport, _ = audio_model(lambda body: sse({"audio": {"transcript": "El reembolso fue emitido.", "data": PCM}}))
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({"conversation": {"api_key": "k", "result_transport": "native_exact"}}, voice, transport=transport)
        canonical = "Recepción simulada registrada. No hubo reembolso."
        talk.remember_result("s", reply)
        events = await talk.turn("s", "es", result=reply)
        assert await anext(events) == {"type": "error"}
        talk.consume_speech("s", canonical)
        await events.aclose()
        with pytest.raises(VoiceError):
            talk.consume_speech("s", canonical)
        assert "s" not in talk._pending
        await talk.close(), await voice.close()
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["http", "read", "oversized_audio", "oversized_caption", "new_active"])
def test_native_exact_response_failures_are_closed_without_a_receipt(failure):
    class FailedNative(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield sse({"audio": {"transcript": reply, "data": PCM}}).replace("data: [DONE]\n\n", "").encode()
            if failure == "read":
                raise httpx.ReadError("scripted native interruption")
            if failure == "new_active":
                talk._active["s"] = "new-active-turn"
            if failure == "oversized_audio":
                yield sse({"audio": {"data": base64.b64encode(b"\0" * MAX_AUDIO_BYTES).decode()}}).encode()
            elif failure == "oversized_caption":
                yield sse({"audio": {"transcript": "x" * 4001}}).encode()
            else:
                yield b"data: [DONE]\n\n"

        async def aclose(self):
            self.closed = True

    async def run():
        nonlocal talk
        from frontend.server.conversation import Conversation
        stream = FailedNative()
        transport = httpx.MockTransport(lambda request: httpx.Response(503 if failure == "http" else 200, stream=stream))
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({"conversation": {"api_key": "k", "result_transport": "native_exact"}}, voice, transport=transport)
        talk.remember_result("s", reply)
        if failure == "http":
            with pytest.raises(VoiceError) as rejected:
                await talk.turn("s", "es", result=reply)
            assert rejected.value.status_code == 503
        else:
            events = [event async for event in await talk.turn("s", "es", result=reply)]
            assert events == ([] if failure == "new_active" else [{"type": "error"}])
        assert stream.closed and "s" not in talk._pending
        assert not any(item["role"] == "assistant" for item in talk._ledgers["s"][1])
        talk.consume_speech("s", reply)
        await talk.close(), await voice.close()
    from frontend.server.conversation import MAX_AUDIO_BYTES
    talk = None
    reply = "Recepción simulada registrada. No hubo reembolso."
    asyncio.run(run())


def test_native_exact_result_reads_all_bounded_parts_and_closing_after_audio_cannot_gain_a_receipt():
    async def run():
        from frontend.server.conversation import Conversation
        reply = "Detalle verificado. " * 100 + "No se movió dinero ni se emitió un reembolso."
        transport, seen = audio_model(lambda body: sse({"audio": {"transcript": reply, "data": PCM}}))
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({"conversation": {"api_key": "k", "result_transport": "native_exact"}}, voice, transport=transport)
        talk.remember_result("s", reply)
        events = await talk.turn("s", "es", result=reply)
        assert (await anext(events))["type"] == "start"
        assert (await anext(events))["text"] == reply
        assert (await anext(events))["type"] == "audio"
        assert seen[0]["messages"][-1]["content"] == reply
        await events.aclose()
        assert "s" not in talk._pending and not any(item["role"] == "assistant" for item in talk._ledgers["s"][1])
        from frontend.server.conversation import _speech_parts
        for part in _speech_parts(reply):
            talk.consume_speech("s", part)
        await talk.close(), await voice.close()
    asyncio.run(run())


def test_canonical_result_reads_every_bounded_chunk_including_the_last_caveat():
    async def run():
        from frontend.server.conversation import Conversation
        inputs = []

        def handler(request):
            assert request.url.path.endswith("/audio/speech")
            inputs.append(json.loads(request.content)["input"])
            return httpx.Response(200, content=base64.b64decode(PCM))

        transport = httpx.MockTransport(handler)
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({}, voice, transport=transport)
        reply = "Detalle verificado. " * 100 + "No se movió dinero ni se emitió un reembolso."
        talk.remember_result("s", reply)
        events = [e async for e in await talk.turn("s", "es", result=reply)]
        assert len(inputs) == 2 and all(len(part) <= 1200 for part in inputs)
        assert " ".join(inputs) == reply
        assert events[-1]["text"] == reply and events[-1]["samples"] == 600
        talk.played("s", events[-1]["turn_id"], 600, True)
        assert talk._ledgers["s"][1][-1]["content"] == reply
        await talk.close(), await voice.close()
    asyncio.run(run())


def test_canonical_result_enforces_24khz_and_restores_safe_fallback_on_start_failure():
    async def run(provider_configs):
        from frontend.server.conversation import Conversation
        transport, seen = providers()
        voice = VoiceService({"providers": provider_configs}, transport=transport)
        talk = Conversation({"conversation": {"api_key": "k"}}, voice, transport=transport)
        reply = "Recepción simulada registrada. No hubo reembolso."
        talk.remember_result("s", reply)
        if len(provider_configs) == 1:
            with pytest.raises(VoiceError) as unavailable:
                await talk.turn("s", "es", result=reply)
            assert unavailable.value.status_code == 503 and not seen
            # The existing dictation fallback can still read the same safe host text.
            talk.consume_speech("s", reply)
        else:
            events = [e async for e in await talk.turn("s", "es", result=reply)]
            assert events[0]["sample_rate"] == 24000
            assert [request.url.host for request in seen] == ["openrouter.ai"]
        await talk.close(), await voice.close()
    lower_rate = {**GPU, "sample_rate": 16000}
    asyncio.run(run([lower_rate]))
    asyncio.run(run([lower_rate, ROUTER]))


@pytest.mark.parametrize("failure", ["transport", "odd_pcm", "interrupted"])
def test_failed_or_interrupted_canonical_synthesis_never_gains_a_playback_receipt(failure):
    class BrokenSpeech(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"\x10\x00" * 300
            raise httpx.ReadError("scripted speech interruption")

    async def run():
        from frontend.server.conversation import Conversation
        def handler(request):
            assert request.url.path.endswith("/audio/speech")
            return (httpx.Response(200, stream=BrokenSpeech()) if failure == "transport" else
                    httpx.Response(200, content=b"x" if failure == "odd_pcm" else base64.b64decode(PCM)))
        transport = httpx.MockTransport(handler)
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({}, voice, transport=transport)
        reply = "Recepción simulada registrada. No hubo reembolso."
        talk.remember_result("s", reply)
        events = await talk.turn("s", "es", result=reply)
        if failure == "interrupted":
            await anext(events), await anext(events), await anext(events)
            await events.aclose()
        else:
            received = [e async for e in events]
            assert received[-1]["type"] == "error"
        assert "s" not in talk._pending
        assert not any(m["role"] == "assistant" for m in talk._ledgers["s"][1])
        await talk.close(), await voice.close()
    asyncio.run(run())


@pytest.mark.parametrize("chunks,content_type", [
    ([b"RI", b"FF" + b"\0" * 40], "audio/pcm"),
    ([b"R", b"I", b"F", b"F" + b"\0" * 40], None),
    ([b" ", b'{"error":"synthesis failed"}'], "application/octet-stream"),
    ([b"    ", b'{"error":"synthesis failed"}'], None),
    ([b'{', b'"error":"synthesis failed"}'], None),
    ([b"\x10\x00" * 300], "audio/wav"),
    ([b"\x10\x00" * 300], "application/json"),
    ([b"ID", b"3" + b"\0" * 40], "application/octet-stream"),
])
def test_container_or_error_speech_body_never_starts_a_canonical_result(chunks, content_type):
    class ScriptedSpeech(httpx.AsyncByteStream):
        async def __aiter__(self):
            for chunk in chunks:
                yield chunk

    async def run():
        from frontend.server.conversation import Conversation
        def handler(request):
            assert request.url.path.endswith("/audio/speech")
            return httpx.Response(200, stream=ScriptedSpeech(),
                                  headers={"content-type": content_type} if content_type else {})
        transport = httpx.MockTransport(handler)
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({}, voice, transport=transport)
        reply = "Recepción simulada registrada. No hubo reembolso."
        talk.remember_result("s", reply)
        with pytest.raises(VoiceError) as rejected:
            await talk.turn("s", "es", result=reply)
        assert rejected.value.status_code == 503 and "s" not in talk._pending
        assert not any(m["role"] == "assistant" for m in talk._ledgers["s"][1])
        await talk.close(), await voice.close()
    asyncio.run(run())


def test_valid_pcm_prefix_split_across_transport_fragments_keeps_exact_samples():
    class SplitSpeech(httpx.AsyncByteStream):
        async def __aiter__(self):
            for chunk in (b"\x10", b"\x00", b"\x10\x00" * 299):
                yield chunk

    async def run():
        from frontend.server.conversation import Conversation
        transport = httpx.MockTransport(lambda request: httpx.Response(
            200, stream=SplitSpeech(), headers={"content-type": "audio/pcm"}))
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({}, voice, transport=transport)
        reply = "Recepción simulada registrada. No hubo reembolso."
        talk.remember_result("s", reply)
        events = [e async for e in await talk.turn("s", "es", result=reply)]
        actual = b"".join(base64.b64decode(e["data"]) for e in events if e["type"] == "audio")
        assert actual == b"\x10\x00" * 300 and events[-1]["samples"] == 300
        talk.played("s", events[-1]["turn_id"], 300, True)
        assert talk._ledgers["s"][1][-1]["content"] == reply
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


@pytest.mark.parametrize("language,text", [
    ("es", "Tranquilo, respira hondo. Todo va a salir bien."),
    ("pt", "Fique tranquilo, respire fundo. Tudo vai ficar bem."),
    ("es", "Estoy preocupado por mi saldo."),
    ("es", "Mi cuenta está bien, me dijeron que el saldo está correcto."),
    ("pt", "Estou preocupado com minha conta."),
    ("es", "No quiero revisar mi cuenta, solo conversar."),
    ("es", "Quiero tranquilizarme por mi saldo."),
    ("pt", "Quero conversar sobre minha conta."),
    ("es", "Mi banco revisa mi cuenta."),
    ("es", "Sí, adelante."),
])
def test_current_smalltalk_cannot_delegate_even_after_bank_history_and_hostile_tool_output(language, text):
    async def run():
        from frontend.server.conversation import Conversation
        transport, seen = audio_model(lambda body: ASKS, heard=text)
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({}, voice, transport=transport)
        previous = [e async for e in await talk.turn("s", language, message="Revisa el saldo de mi cuenta.")]
        talk.played("s", previous[-1]["turn_id"], previous[-1]["samples"], True)
        current = [e async for e in await talk.turn("s", language, audio=wav())]
        assert seen[-1]["tool_choice"] == "none" and seen[-1]["tools"] == []
        assert "Nunca conviertas tranquilidad" in seen[-1]["messages"][0]["content"]
        assert {"type": "heard", "text": text} in current
        assert not any(e["type"] == "delegate" for e in current)
        assert current[-1]["type"] == "complete"
        assert talk._ledgers["s"][1][-1] == {"role": "user", "content": text}
        await talk.close(), await voice.close()
    asyncio.run(run())


@pytest.mark.parametrize("language,text", [
    ("es", "¿Cuánto tengo en mi cuenta de ahorros?"),
    ("es", "No reconozco este cargo."),
    ("es", "Ayúdame a comparar este comercio con mis recibos y preparar el próximo paso."),
    ("pt", "Qual é o saldo da minha conta?"),
    ("pt", "Não reconheço esta cobrança."),
    ("pt", "Ajude-me a comparar este comércio com meus recibos."),
    ("es", "¿Qué comercio aparece en este cargo?"),
    ("pt", "Qual o valor desta transação?"),
])
@pytest.mark.parametrize("audio", [False, True])
def test_explicit_current_bank_request_delegates_exact_words_not_model_rewrite(language, text, audio):
    async def run():
        from frontend.server.conversation import Conversation
        transport, seen = audio_model(lambda body: ASKS, heard=text)
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({}, voice, transport=transport)
        current = [e async for e in await talk.turn("s", language, **({"audio": wav()} if audio else {"message": text}))]
        assert seen[-1]["tool_choice"] == "auto" and seen[-1]["tools"][0]["function"]["name"] == "consultar_savia"
        assert [e for e in current if e["type"] == "delegate"] == [{"type": "delegate", "request": text}]
        assert current[-1]["type"] == "complete"
        assert not any(m["role"] == "assistant" for m in talk._ledgers["s"][1])
        talk.played("s", current[-1]["turn_id"], current[-1]["samples"], True)
        assert talk._ledgers["s"][1][-1] == {"role": "assistant", "content": "Claro, lo reviso."}
        busy = [e async for e in await talk.turn("s", language, message=text, working=True)]
        assert seen[-1]["tool_choice"] == "none" and seen[-1]["tools"] == []
        assert not any(e["type"] == "delegate" for e in busy)
        await talk.close(), await voice.close()
    asyncio.run(run())


def test_failed_final_recognition_keeps_native_conversation_without_tools_or_added_asr():
    async def run():
        from frontend.server.conversation import Conversation
        calls = []
        def handler(request):
            calls.append(request.url.path)
            if request.url.path.endswith("/audio/transcriptions"):
                return httpx.Response(503)
            body = json.loads(request.content)
            assert body["tools"] == [] and body["tool_choice"] == "none"
            return httpx.Response(200, text=ASKS)
        transport = httpx.MockTransport(handler)
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({}, voice, transport=transport)
        events = [e async for e in await talk.turn("s", "es", audio=wav())]
        assert len([p for p in calls if p.endswith("/audio/transcriptions")]) == 1
        assert events[-1]["type"] == "complete" and not any(e["type"] == "delegate" for e in events)
        await talk.close(), await voice.close()
    asyncio.run(run())


@pytest.mark.parametrize("script", [
    ASKS.replace("consultar_savia", "invented_tool"),
    sse({"audio": {"data": PCM}}, {"tool_calls": [{"index": 0, "function": {"name": "consultar_savia", "arguments": "not JSON"}}]}),
    sse({"audio": {"data": PCM}}, {"tool_calls": [{"index": 0, "function": {"name": "consultar_savia", "arguments": '{"solicitud": 42}'}}]}),
])
def test_unknown_or_malformed_model_tool_cannot_delegate_an_explicit_request(script):
    async def run():
        from frontend.server.conversation import Conversation
        transport, _ = audio_model(lambda body: script)
        voice = VoiceService({"providers": [ROUTER]}, transport=transport)
        talk = Conversation({}, voice, transport=transport)
        events = [e async for e in await talk.turn("s", "es", message="Revisa mi saldo.")]
        assert events[-1]["type"] == "complete" and not any(e["type"] == "delegate" for e in events)
        await talk.close(), await voice.close()
    asyncio.run(run())
