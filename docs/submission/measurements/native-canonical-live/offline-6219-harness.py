"""Join exact exported RC card authority to canonical voice using fictional state.

Run with existing Python 3.13 dependencies. All application imports are from the
immutable export; only provider transport and the unused language model are
replaced. Socket connections are denied throughout the qualification.
"""
from __future__ import annotations

import base64
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import traceback
from unittest.mock import patch
import uuid

sys.dont_write_bytecode = True
SOURCE = Path("C:/Users/Moe/.codex/tmp/savia-native-runtime-6219bc81a8a4/application")
OUT = Path("C:/Users/Moe/.codex/tmp/savia-joined-card-native-offline-6219.json")
REVISION = "6219bc81a8a4c7f2936769e7727e5146dd2713d0"
ORIGIN = "http://127.0.0.1:43905"
PCM = b"\x10\x00" * 9600
sys.path.insert(0, str(SOURCE))

import httpx
from fastapi.testclient import TestClient
import frontend.server.app as app_module
from deploy.rc import run as rc
from dispute_workflow.model import FlujoModel


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def source_proof() -> dict:
    manifest = json.loads((SOURCE / "source-manifest.json").read_text())
    assert manifest["git_head"] == REVISION
    assert len(manifest["files"]) == 183
    for relative, wanted in manifest["files"].items():
        assert digest((SOURCE / relative).read_bytes()) == wanted, relative
    return {"git_head": manifest["git_head"], "git_tree": manifest["git_tree"],
            "manifest_sha256": digest((SOURCE / "source-manifest.json").read_bytes()),
            "source_files_verified": len(manifest["files"]),
            "source_files_sha256": manifest["files"]}


class FragmentedNativeSSE(httpx.AsyncByteStream):
    def __init__(self, script):
        self.script = script

    async def __aiter__(self):
        cut = len(self.script) // 2
        deltas = [
            {"audio": {"transcript": self.script[:cut], "data": base64.b64encode(PCM[:1]).decode()}},
            {"audio": {"transcript": self.script[cut:], "data": base64.b64encode(PCM[1:8193]).decode()}},
            {"audio": {"data": base64.b64encode(PCM[8193:]).decode()}},
        ]
        wire = ("".join("data: " + json.dumps({"choices": [{"index": 0, "delta": delta}]},
                     ensure_ascii=False) + "\n\n" for delta in deltas) + "data: [DONE]\n\n").encode()
        for offset in range(0, len(wire), 37):
            yield wire[offset:offset + 37]


def qualify() -> dict:
    source_before = source_proof()
    assert Path(rc.__file__).resolve() == (SOURCE / "deploy/rc/run.py").resolve()
    assert Path(app_module.__file__).resolve() == (SOURCE / "frontend/server/app.py").resolve()
    outbound = []
    network_attempts = []
    language_attempts = []
    internal_socketpairs = []
    steps = []
    cases = []

    original_connect = socket.socket.connect
    socketpair_code = getattr(socket.socketpair, "__code__", None)

    def deny_connect(sock, address, *args, **kwargs):
        # Windows asyncio creates its internal self-pipe through the standard
        # library's authenticated loopback socketpair. Permit only that exact
        # implementation callsite; deny every application/provider connection.
        if socketpair_code is not None and sys._getframe(1).f_code is socketpair_code:
            assert address[0] in {"127.0.0.1", "::1"}
            internal_socketpairs.append("stdlib_loopback_self_pipe")
            return original_connect(sock, address, *args, **kwargs)
        network_attempts.append("socket_connection_denied")
        raise AssertionError("No network connection is permitted by this qualification")

    async def deny_language(self, stage, system, user):
        language_attempts.append(stage)
        raise AssertionError("Card API qualification must not invoke a language model")

    def speech(request):
        body = json.loads(request.content)
        assert request.method == "POST" and request.url.path == "/api/v1/chat/completions"
        assert body["model"] == "openai/gpt-audio" and body["modalities"] == ["text", "audio"]
        assert body["audio"] == {"voice": "coral", "format": "pcm16"} and body["stream"] is True
        assert len(body["messages"]) == 2 and body["messages"][0]["role"] == "system"
        assert "exact text-to-speech reader" in body["messages"][0]["content"]
        assert body["messages"][1]["role"] == "user" and isinstance(body["messages"][1]["content"], str)
        assert "tools" not in body and "tool_choice" not in body
        script = body["messages"][1]["content"]
        outbound.append({"method": request.method, "path": request.url.path,
                         "input": script, "model": body["model"], "voice": body["audio"]["voice"],
                         "format": body["audio"]["format"], "request_kind": "mocked isolated native_exact script reader",
                         "history_messages": 0, "tool_definitions": 0, "provider_usage": None, "provider_cost_usd": None})
        return httpx.Response(200, stream=FragmentedNativeSSE(script), headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(speech)
    actual_create_app = app_module.create_app

    def create_mocked_app(*args, **kwargs):
        assert "voice_transport" not in kwargs
        return actual_create_app(*args, **kwargs, voice_transport=transport)

    voice_config = rc.native_voice_config()
    assert voice_config["conversation"]["result_transport"] == "native_exact"
    for provider in voice_config["providers"]:
        provider.pop("api_key_env", None)
        provider["api_key"] = "offline-scripted-provider-key"
    voice_config["conversation"].pop("api_key_env", None)
    voice_config["conversation"]["api_key"] = "offline-scripted-provider-key"

    def request(client, label, method, path, *, expected=200, payload=None):
        response = client.request(method, path, json=payload, headers={"Origin": ORIGIN})
        steps.append({"step": label, "method": method, "path": path,
                      "status": response.status_code, "expected_status": expected})
        assert response.status_code == expected, (label, response.status_code, response.text[:500])
        return response

    with tempfile.TemporaryDirectory(prefix="savia-joined-card-native-offline-6219.fixture.", dir=OUT.parent) as temp:
        fixture_root = Path(temp).resolve() / "fictional-rc"
        fixture_root.mkdir(mode=0o700)
        with patch.object(socket.socket, "connect", deny_connect), \
                patch.object(socket.socket, "connect_ex", deny_connect), \
                patch.dict(os.environ, {"SAVIA_VOICE_CONFIG_FILE": ""}), \
                patch.object(FlujoModel, "__call__", deny_language), \
                patch.object(app_module, "create_app", create_mocked_app):
            with redirect_stdout(io.StringIO()):
                rc.prepare(fixture_root)
                (fixture_root / "instance").mkdir(mode=0o700, exist_ok=True)
                fixture = json.loads((fixture_root / "fixture.json").read_text())
                app, bank = rc.application(fixture_root, port=43905,
                    base_url="http://127.0.0.1:1", model_id="offline-unused-language-model",
                    provider="openrouter", provider_key="offline-unused-language-key",
                    public_origin=ORIGIN, voice_config=voice_config)
            try:
                with TestClient(app, base_url=ORIGIN) as client:
                    request(client, "unauthenticated_card_denied", "POST", "/api/cards/block", expected=401,
                            payload={"product_reference": "prod_" + "a" * 24, "operation": "status"})
                    for language, profile, foreign_profile, caveat in (
                        ("es", "mexico", "colombia", "Ningún banco real fue modificado."),
                        ("pt", "colombia", "mexico", "Nenhum banco real foi alterado."),
                    ):
                        request(client, language + "_login", "POST", "/api/auth/login",
                                payload={"profile": profile, "code": fixture["demo_code"]})
                        overview = request(client, language + "_overview", "GET", "/api/overview").json()
                        target = next(p["reference"] for p in overview["products"] if p["type"] == "Tarjeta Crédito")
                        status = request(client, language + "_initial_status", "POST", "/api/cards/block",
                            payload={"product_reference": target, "operation": "status", "language": language}).json()
                        assert status["state"] == "card_unblocked"
                        prepared = request(client, language + "_prepare", "POST", "/api/cards/block", payload={
                            "product_reference": target, "operation": "prepare", "request_id": str(uuid.uuid4()),
                            "language": language}).json()
                        assert prepared["state"] == "pending_confirmation"
                        confirmation = {"product_reference": target, "operation": "confirm",
                                        "pending_handle": prepared["pending_handle"], "language": language}
                        request(client, language + "_missing_consent_denied", "POST", "/api/cards/block",
                                expected=422, payload=confirmation)
                        unchanged = request(client, language + "_before_confirm_status", "POST", "/api/cards/block",
                            payload={"product_reference": target, "operation": "status", "language": language}).json()
                        assert unchanged["state"] == "card_unblocked"
                        verified = request(client, language + "_explicit_confirm", "POST", "/api/cards/block",
                                payload={**confirmation, "confirmed": True}).json()
                        assert verified["state"] == "card_block_verified"
                        assert verified["receipt"]["status"] == "blocked" and verified["receipt"]["simulated"] is True
                        actual_status = request(client, language + "_canonical_owned_status", "POST", "/api/cards/block",
                            payload={"product_reference": target, "operation": "status", "language": language}).json()
                        assert actual_status["state"] == "card_block_verified"
                        assert actual_status["receipt"] == verified["receipt"]
                        message = actual_status["message"]
                        assert caveat in message
                        count_before = len(outbound)
                        request(client, language + "_tampered_result_denied", "POST", "/api/voice/turn", expected=409,
                                payload={"language": language, "result": message + " Reembolso confirmado."})
                        # Use a client without entering a second lifespan; app is already running.
                        foreign = TestClient(app, base_url=ORIGIN)
                        try:
                            request(foreign, language + "_foreign_login", "POST", "/api/auth/login", payload={
                                "profile": foreign_profile, "code": fixture["demo_code"]})
                            request(foreign, language + "_foreign_card_denied", "POST", "/api/cards/block", expected=404,
                                    payload={"product_reference": target, "operation": "status", "language": language})
                            request(foreign, language + "_foreign_result_denied", "POST", "/api/voice/turn", expected=409,
                                    payload={"language": language, "result": message})
                            assert len(outbound) == count_before
                            response = request(client, language + "_canonical_result", "POST", "/api/voice/turn",
                                               payload={"language": language, "result": message})
                            events = [json.loads(line) for line in response.text.splitlines()]
                            assert events[0]["type"] == "start" and events[0]["sample_rate"] == 24000
                            assert events[-1]["type"] == "complete" and events[-1]["text"] == message
                            assert [e["text"] for e in events if e["type"] == "caption"] == [message]
                            returned_pcm = b"".join(base64.b64decode(e["data"]) for e in events if e["type"] == "audio")
                            assert returned_pcm == PCM and events[-1]["samples"] == len(PCM) // 2
                            assert all(e["type"] not in {"delegate", "error"} for e in events)
                            assert len(outbound) == count_before + 1 and outbound[-1]["input"] == message
                            current = app.state.bank_state.session(client.cookies.get("flujo_bank_session"))
                            assert not any(m["role"] == "assistant" for m in app.state.conversation._ledgers[current.id][1])
                            ack = {"turn_id": events[-1]["turn_id"], "played_samples": events[-1]["samples"], "complete": True}
                            request(foreign, language + "_foreign_ack_denied", "POST", "/api/voice/played", expected=409, payload=ack)
                            request(client, language + "_wrong_sample_ack_denied", "POST", "/api/voice/played", expected=409,
                                    payload={**ack, "played_samples": ack["played_samples"] - 1})
                            request(client, language + "_exact_ack", "POST", "/api/voice/played", payload=ack)
                            assert app.state.conversation._ledgers[current.id][1][-1] == {"role": "assistant", "content": message}
                            request(client, language + "_reused_ack_denied", "POST", "/api/voice/played", expected=409, payload=ack)
                            request(client, language + "_replayed_result_denied", "POST", "/api/voice/turn", expected=409,
                                    payload={"language": language, "result": message})
                            receipt = request(client, language + "_card_receipt_readback", "POST", "/api/cards/block", payload={
                                **confirmation, "operation": "receipt"}).json()
                            assert receipt["receipt"] == verified["receipt"]
                            request(client, language + "_readback_does_not_reissue_voice", "POST", "/api/voice/turn", expected=409,
                                    payload={"language": language, "result": receipt["message"]})
                            assert len(outbound) == count_before + 1
                            cases.append({"language": language, "fictional_profile": profile,
                                "verified_state": actual_status["state"], "simulated": True,
                                "result_origin": "actual owned-card status API response registered by the RC host",
                                "native_result_transport": "native_exact",
                                "canonical_host_message": message, "canonical_host_message_sha256": digest(message.encode()),
                                "speech_request_equal_to_actual_api_message": True, "caption_equal_to_actual_api_message": True,
                                "no_real_bank_caveat_preserved": True, "sample_rate": 24000,
                                "returned_pcm_bytes": len(returned_pcm), "returned_pcm_samples": len(returned_pcm) // 2,
                                "returned_pcm_sha256": digest(returned_pcm), "fragmented_pcm_preserved": True,
                                "exact_ack_once": True, "assistant_history_added_only_after_ack": True,
                                "tampered_result_denied": True, "foreign_card_result_and_ack_denied": True,
                                "receipt_readback_equal": True, "readback_cannot_reissue_consumed_voice": True})
                        finally:
                            foreign.close()
                        request(client, language + "_logout", "POST", "/api/auth/logout", expected=204, payload={})
                    with bank.store.connect() as db:
                        ledger_count = db.execute("SELECT count(*) FROM sandbox_card_blocks").fetchone()[0]
                    assert ledger_count == 2
                    assert not language_attempts and not network_attempts
                    assert len(outbound) == 2
            finally:
                bank.close()
    source_after = source_proof()
    assert source_before == source_after
    return {"schema": "savia-joined-card-native-exact-offline/v1", "passed": True,
            "observed_at": datetime.now(timezone.utc).isoformat(), "source": source_after,
            "harness_sha256": digest(Path(__file__).read_bytes()),
            "runtime": {"python_executable": sys.executable, "python_version": sys.version,
                        "dependencies": {name: importlib.metadata.version(name) for name in
                                         ("fastapi", "httpx", "duckdb", "cryptography", "pydantic")}},
            "qualification": {"fixture": "new disposable generated fiction from exact RC prepare/application",
                              "app_import_root": str(SOURCE), "real_project_banking_service_in_process": True,
                              "live_public_state_touched": False, "real_provider_calls": 0,
                              "socket_connection_attempts": len(network_attempts), "workflow_language_model_calls": len(language_attempts),
                              "stdlib_internal_loopback_socketpairs": len(internal_socketpairs),
                              "mocked_native_exact_completions_for_results": len(outbound), "mocked_native_exact_calls": len(outbound),
                              "disposable_fictional_card_blocks": ledger_count,
                              "fixture_automatically_removed": True, "source_bytes_unchanged": True},
            "cases": cases, "http_checks": steps, "http_check_count": len(steps),
            "mocked_native_exact_requests": outbound, "provider_usage": None, "provider_cost_usd": None,
            "usage_cost_scope": "Unavailable: scripted native SSE contains no usage or cost metadata; no real provider call or cost inference.",
            "limits": ["Offline ASGI/cookie/host/API integration with scripted native SSE transport; no live provider or exact-transcript availability claim.",
                       "No graphical browser, physical playback, microphone/AEC, waveform/text alignment or human comprehension measurement.",
                       "Returned PCM samples and simulated acknowledgment verify protocol accounting, not that audio was physically heard.",
                       "No real bank action; exactly two card blocks occur only in the removed generated fictional ledger.",
                       "The new native_exact provider transport and deployment decision require separate live evidence."]}


if __name__ == "__main__":
    try:
        report = qualify()
    except Exception as exc:
        report = {"schema": "savia-joined-card-native-exact-offline/v1", "passed": False,
                  "observed_at": datetime.now(timezone.utc).isoformat(), "error_type": type(exc).__name__,
                  "error": str(exc), "traceback": traceback.format_exc(),
                  "harness_sha256": digest(Path(__file__).read_bytes()), "live_public_state_touched": False}
        OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        raise
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "cases": len(report["cases"]),
                      "http_checks": report["http_check_count"], "mocked_native_exact_calls": 2,
                      "source_files_verified": report["source"]["source_files_verified"], "receipt": str(OUT)}))
