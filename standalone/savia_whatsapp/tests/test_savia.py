import asyncio
import base64
import io
import json
import wave

import httpx
import pytest

from standalone.savia_whatsapp.savia import SaviaClient, SaviaError


def fixture(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "QUALIFICATION_SYNTHETIC.json").write_text('{"synthetic":true}')
    file = tmp_path / "fixture.json"
    file.write_text(json.dumps({"root": str(tmp_path), "source": str(source),
                               "demo_code": "private-demo-code", "profiles": {"mexico": {}}}))
    return file


def wav(frames=1600, channels=1, rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"\x01\x00" * frames * channels)
    return output.getvalue()


def events(*, caption="Hola.", delegated=None, heard=None, bad_samples=False):
    data = [{"type": "start", "sample_rate": 24000, "turn_id": "a" * 24}]
    if heard is not None:
        data.append({"type": "heard", "text": heard})
    data += [{"type": "caption", "text": caption},
             {"type": "audio", "data": base64.b64encode(b"\x01\x00" * 100).decode()}]
    if delegated is not None:
        data.append({"type": "delegate", "request": delegated})
    data.append({"type": "complete", "text": caption, "turn_id": "a" * 24,
                 "samples": 101 if bad_samples else 100})
    return data


def transport(handler):
    seen = []

    def handle(request):
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        assert request.headers["origin"] == "http://127.0.0.1:43971"
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"authenticated": True, "profile": {"id": "mexico"}},
                                  headers={"set-cookie": "flujo_bank_session=private-session; Path=/; HttpOnly"})
        assert request.headers["cookie"] == "flujo_bank_session=private-session"
        if request.url.path == "/api/voice/played":
            assert body == {"turn_id": "a" * 24, "played_samples": 0, "complete": False}
            return httpx.Response(200, json=None)
        result = handler(request.url.path, body)
        if isinstance(result, list):
            return httpx.Response(200, content="\n".join(json.dumps(item) for item in result),
                                  headers={"content-type": "application/x-ndjson"})
        return result

    return httpx.MockTransport(handle), seen


def test_native_smalltalk_has_exact_wav_and_never_acknowledges_playback(tmp_path):
    scripted, seen = transport(lambda path, body: events())

    async def run():
        async with SaviaClient("http://127.0.0.1:43971", fixture(tmp_path), transport=scripted) as client:
            return await client.converse(message="Hola")

    reply = asyncio.run(run())
    assert reply.text == "Hola." and reply.delegated_request is None
    turn = reply.voice_turns[0]
    with wave.open(io.BytesIO(turn.wav)) as audio:
        assert (audio.getframerate(), audio.getnframes(), audio.getnchannels()) == (24000, 100, 1)
    assert [path for path, _ in seen] == ["/api/auth/login", "/api/voice/turn", "/api/voice/played"]


def test_audio_delegation_uses_exact_authenticated_host_reply_for_narration(tmp_path):
    request_text, exact_reply = "No reconozco este cargo", "El cargo registrado es de 20 MXN."

    def handle(path, body):
        if path == "/api/chat/messages":
            assert body == {"message": request_text, "language": "es"}
            return httpx.Response(200, json={"reply": exact_reply})
        assert path == "/api/voice/turn"
        if "audio" in body:
            assert base64.b64decode(body["audio"]) == wav()
            return events(caption="Voy a consultar.", delegated=request_text, heard=request_text)
        assert body == {"language": "es", "result": exact_reply}
        return events(caption="Son veinte pesos mexicanos.")

    scripted, seen = transport(handle)

    async def run():
        async with SaviaClient("http://127.0.0.1:43971", fixture(tmp_path), transport=scripted) as client:
            return await client.converse(audio_wav=wav())

    reply = asyncio.run(run())
    assert reply.text == exact_reply and reply.delegated_request == reply.heard_text == request_text
    assert [turn.caption for turn in reply.voice_turns] == ["Voy a consultar.", "Son veinte pesos mexicanos."]
    assert all(not path.startswith("/api/action") for path, _ in seen)
    assert len([body for path, body in seen if path == "/api/voice/played" and body["complete"] is False]) == 2


@pytest.mark.parametrize("failure", ["truncated", "sample_mismatch", "error", "changed_delegate", "odd_pcm", "bad_json"])
def test_incomplete_or_malformed_voice_never_reaches_bank_or_ack(tmp_path, failure):
    data = events(bad_samples=failure == "sample_mismatch")
    if failure == "truncated":
        data.pop()
    elif failure == "error":
        data[-1] = {"type": "error"}
    elif failure == "changed_delegate":
        data = events(delegated="Revisa mi saldo")
    elif failure == "odd_pcm":
        data[2]["data"] = base64.b64encode(b"\x00").decode()
    elif failure == "bad_json":
        data = httpx.Response(200, content="{broken", headers={"content-type": "application/x-ndjson"})
    scripted, seen = transport(lambda path, body: data)

    async def run():
        async with SaviaClient("http://127.0.0.1:43971", fixture(tmp_path), transport=scripted) as client:
            await client.converse(message="Hola")

    with pytest.raises(SaviaError):
        asyncio.run(run())
    assert [path for path, _ in seen] == ["/api/auth/login", "/api/voice/turn"]


@pytest.mark.parametrize("input_data", [b"not audio", wav(channels=2), wav(frames=16000 * 31), wav(rate=6000)],
                         ids=["not_wav", "stereo", "too_long", "invalid_rate"])
def test_invalid_input_is_rejected_before_login_or_provider_call(tmp_path, input_data):
    scripted, seen = transport(lambda path, body: events())

    async def run():
        async with SaviaClient("http://127.0.0.1:43971", fixture(tmp_path), transport=scripted) as client:
            await client.converse(audio_wav=input_data)

    with pytest.raises(SaviaError):
        asyncio.run(run())
    assert seen == []


def test_auth_error_hides_response_body_and_secret(tmp_path):
    scripted = httpx.MockTransport(lambda request: httpx.Response(401, json={"detail": "private-demo-code"}))

    async def run():
        async with SaviaClient("http://127.0.0.1:43971", fixture(tmp_path), transport=scripted) as client:
            await client.login()

    with pytest.raises(SaviaError, match="HTTP 401") as error:
        asyncio.run(run())
    assert "private-demo-code" not in str(error.value)


def test_fixture_without_synthetic_provenance_cannot_login(tmp_path):
    file = fixture(tmp_path)
    (tmp_path / "source/QUALIFICATION_SYNTHETIC.json").unlink()
    scripted, seen = transport(lambda path, body: events())

    async def run():
        async with SaviaClient("http://127.0.0.1:43971", file, transport=scripted) as client:
            await client.login()

    with pytest.raises(SaviaError, match="fictional fixture"):
        asyncio.run(run())
    assert seen == []


def test_actual_rc_routes_register_exact_reply_and_keep_delivery_out_of_heard_history(tmp_path):
    """Use the actual RC host/voice routes with generated data and scripted providers."""
    from dataclasses import replace
    from unittest.mock import patch

    api_tests = pytest.importorskip("frontend.tests.test_api")
    from frontend.server.app import create_app
    from frontend.server.chat import ChatService
    from frontend.tests.direct_host_fixtures import attach_direct_fakes, make_direct_config
    from frontend.tests.test_voice import ASKS, TELLS, audio_model

    settings = api_tests.settings.__wrapped__(tmp_path)
    chat = make_direct_config(tmp_path / "direct", principal_customers={
        "synthetic-mexico": "private-customer-mx", "synthetic-colombia": "private-customer-co",
        "synthetic-argentina": "private-customer-ar"})
    provider, provider_calls = audio_model(lambda body: ASKS if body["tool_choice"] == "auto" else TELLS)
    configured = replace(settings, public_origin="http://127.0.0.1:43971", chat=chat,
                         voice={"conversation": {"api_key": "scripted-test-only-key"}})
    file = fixture(tmp_path)
    private = json.loads(file.read_text())
    private["demo_code"] = settings.demo_code
    file.write_text(json.dumps(private))
    services = []

    def construct(config, state_dir):
        service = ChatService(config, state_dir)
        bank, language = attach_direct_fakes(service)
        services.append((service, bank, language))
        return service

    async def run():
        app = create_app(configured, voice_transport=provider)
        paths = []

        @app.middleware("http")
        async def observe(request, call_next):
            paths.append(request.url.path)
            return await call_next(request)

        async with app.router.lifespan_context(app):
            async with SaviaClient("http://127.0.0.1:43971", file,
                                   transport=httpx.ASGITransport(app=app)) as client:
                reply = await client.converse(message="¿Cuál es el valor de esta transacción?")
                assert reply.delegated_request == "¿Cuál es el valor de esta transacción?"
                assert len(reply.voice_turns) == 2 and reply.text
                # Caller narration was accepted only because the real chat route registered it.
                results = next(iter(app.state.conversation._results.values()))[1]
                assert results[reply.text] is True
                assert not app.state.conversation._pending
                history = next(iter(app.state.conversation._ledgers.values()))[1]
                assert not any(message["role"] == "assistant" for message in history)
                assert paths == ["/api/auth/login", "/api/voice/turn", "/api/voice/played",
                                 "/api/chat/messages", "/api/voice/turn", "/api/voice/played"]
                return reply

    with patch("frontend.server.chat.ChatService", new=construct):
        reply = asyncio.run(run())
    assert services[0][2].calls and not services[0][1].calls
    assert len(provider_calls) == 2 and provider_calls[-1]["tool_choice"] == "none"
    narrated = json.loads(provider_calls[-1]["messages"][-1]["content"].split("\n", 1)[1])
    assert narrated["respuesta"] == reply.text
