"""Authored wire tests using in-memory HTTPX transports, never a bank service."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
import ssl
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import httpx
import jwt
import rfc8785
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from frontend.server.bank_rpc import ASSERTION_META, BankContext, BankRPC, BankRPCError, PROTOCOL_VERSION
from frontend.tests.direct_host_fixtures import GENERATED_LEDGER_GENERATION, make_direct_config


def tool_response(request, body, value, *, error=False):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {
        "structuredContent": value, "content": [{"type": "text", "text": json.dumps(value)}],
        "isError": error}}, request=request)


class BankRPCTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.key = Ed25519PrivateKey.generate()
        filename = Path(self.directory.name) / "private-bank-host.pem"
        filename.write_bytes(self.key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        ca_file = make_direct_config(Path(self.directory.name))["bank"]["ca_file"]
        self.config = {"base_url": "https://banking-mcp:8000", "service_token": "b" * 48,
                       "issuer": "hackathon-bank-host", "audience": "banking-mcp", "kid": "bank-host-v1",
                       "signing_key_file": str(filename), "ca_file": ca_file}
        self.context = BankContext("subject-a", "host-bank-session-a", "host-bank-conversation-a",
                                   str(uuid.uuid4()), "a" * 40, int(time.time()) + 3600,
                                   GENERATED_LEDGER_GENERATION)
        self.requests = []
        self.value = {"state": "created", "receipt": None}
        self.tool_handler = None
        self.init_handler = None

    def tearDown(self):
        self.directory.cleanup()

    def respond(self, request):
        body = json.loads(request.content)
        self.requests.append((request, body))
        if request.url.path == "/internal/revoke":
            return httpx.Response(200, json={"revoked": True})
        self.assertEqual(request.url.path, "/mcp")
        if body["method"] == "initialize":
            if self.init_handler:
                return self.init_handler(request, body)
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                "serverInfo": {"name": "banking-mcp", "version": "1.0.0"}}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202, content=b"")
        self.assertEqual(body["method"], "tools/call")
        return self.tool_handler(request, body) if self.tool_handler else tool_response(request, body, self.value)

    def rpc(self):
        return BankRPC(self.config, transport=httpx.MockTransport(self.respond))

    def calls(self):
        return [(request, body) for request, body in self.requests if body.get("method") == "tools/call"]

    def claims(self, token):
        return jwt.decode(token, self.key.public_key(), algorithms=["EdDSA"],
                          issuer=self.config["issuer"], audience=self.config["audience"])

    async def test_standard_stateless_handshake_and_exact_signed_arguments(self):
        args = {"transaction_id": "private-owned-id", "snapshot": "build-a", "request_id": str(uuid.uuid4())}
        raw = await self.rpc().call("prepare_unrecognized_charge", args, self.context)
        self.assertEqual(raw, self.value)  # No fabricated public pending/verified projection.
        self.assertEqual([body["method"] for _, body in self.requests],
                         ["initialize", "notifications/initialized", "tools/call"])
        initialize = self.requests[0][1]
        self.assertEqual(initialize["params"]["capabilities"], {})
        self.assertEqual(initialize["params"]["protocolVersion"], PROTOCOL_VERSION)
        self.assertNotIn("id", self.requests[1][1])
        request, body = self.calls()[0]
        self.assertEqual(body["params"]["arguments"], args)
        claims = self.claims(body["params"]["_meta"][ASSERTION_META])
        self.assertEqual(jwt.get_unverified_header(body["params"]["_meta"][ASSERTION_META]),
                         {"alg": "EdDSA", "typ": "bank-mcp+jwt", "kid": "bank-host-v1"})
        self.assertEqual(set(claims), {"iss", "aud", "sub", "iat", "nbf", "exp", "jti", "session_id",
            "conversation_id", "run_id", "graph_revision", "tool", "scope", "args_sha256", "ledger_generation"})
        self.assertEqual(claims["ledger_generation"], GENERATED_LEDGER_GENERATION)
        self.assertEqual(claims["args_sha256"], hashlib.sha256(rfc8785.dumps(args)).hexdigest())
        self.assertEqual((claims["sub"], claims["session_id"], claims["conversation_id"]),
                         (self.context.subject, self.context.session_id, self.context.conversation_id))
        self.assertEqual((claims["run_id"], claims["graph_revision"]),
                         (self.context.operation_id, self.context.host_revision))
        self.assertEqual(claims["scope"], ["bank:prepare"])
        self.assertEqual(claims["nbf"], claims["iat"])
        self.assertTrue(0 < claims["exp"] - claims["iat"] <= 60)
        for seen, _ in self.requests:
            self.assertEqual(seen.headers["authorization"], "Bearer " + self.config["service_token"])
            self.assertEqual(seen.headers["accept"], "application/json, text/event-stream")
            self.assertNotIn("X-Flujo-User-Assertion", seen.headers)
            self.assertNotIn("MCP-Session-Id", seen.headers)
        self.assertEqual(request.headers["MCP-Protocol-Version"], PROTOCOL_VERSION)

    async def test_fixed_current_tool_names_and_scopes(self):
        expected = {"banking_status": "bank:read", "list_my_transactions": "bank:read",
            "get_my_transaction": "bank:read", "prepare_unrecognized_charge": "bank:prepare",
            "confirm_simulated_intake": "bank:write", "read_intake_receipt": "bank:receipt",
            "create_verified_handoff": "bank:handoff", "read_verified_handoff": "bank:handoff-read"}
        rpc = self.rpc()
        for tool, scope in expected.items():
            with self.subTest(tool=tool):
                await rpc.call(tool, {}, self.context)
                claims = self.claims(self.calls()[-1][1]["params"]["_meta"][ASSERTION_META])
                self.assertEqual((claims["tool"], claims["scope"]), (tool, [scope]))
        self.assertEqual(len(self.calls()), len(expected))
        for tool in ["confirm_unrecognized_charge", "get_unrecognized_charge_receipt", "create_human_handoff",
                     "get_human_handoff", "revoke_session", "arbitrary_model_tool"]:
            with self.subTest(forbidden=tool), self.assertRaises(BankRPCError) as error:
                await rpc.call(tool, {}, self.context)
            self.assertEqual(error.exception.code, "bank_tool_forbidden")
        self.assertEqual(len(self.calls()), len(expected))

    async def test_repeated_caller_attempts_keep_tuple_but_get_fresh_jtis(self):
        args = {"transaction_id": "private-owned-id", "snapshot": "build-a", "request_id": str(uuid.uuid4())}
        rpc = self.rpc()
        await rpc.call("prepare_unrecognized_charge", args, self.context)
        await rpc.call("prepare_unrecognized_charge", args, self.context)
        first, second = [self.claims(body["params"]["_meta"][ASSERTION_META]) for _, body in self.calls()]
        self.assertNotEqual(first["jti"], second["jti"])
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["args_sha256"], second["args_sha256"])
        self.assertEqual([body["params"]["arguments"] for _, body in self.calls()], [args, args])

    async def test_arguments_are_frozen_before_handshake_await(self):
        args = {"unanswered_questions": ["¿Qué necesitas?"], "reason": "customer_request"}
        original = self.respond
        def change(request, body):
            args["unanswered_questions"].append("replacement")
            self.init_handler = None
            return original(request)
        self.init_handler = change
        await self.rpc().call("create_verified_handoff", args, self.context)
        sent = self.calls()[0][1]["params"]["arguments"]
        self.assertEqual(sent["unanswered_questions"], ["¿Qué necesitas?"])

    async def test_session_deadline_bounds_claim_and_expired_context_sends_nothing(self):
        context = replace(self.context, session_expires=int(time.time()) + 10)
        await self.rpc().call("list_my_transactions", {}, context)
        claims = self.claims(self.calls()[0][1]["params"]["_meta"][ASSERTION_META])
        self.assertLessEqual(claims["exp"], context.session_expires)
        self.requests.clear()
        with self.assertRaises(BankRPCError) as error:
            await self.rpc().call("list_my_transactions", {}, replace(context, session_expires=1))
        self.assertEqual(error.exception.code, "bank_authority_expired")
        self.assertFalse(error.exception.possibly_sent)
        self.assertEqual(self.requests, [])

    async def test_expiry_after_initialize_prevents_tool_dispatch(self):
        clock = {"now": time.time()}
        def initialized(request, body):
            clock["now"] = self.context.session_expires + 1
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                "serverInfo": {"name": "banking-mcp", "version": "1.0.0"}}})
        self.init_handler = initialized
        # Replace only this module's clock reference; HTTPX keeps real time.
        with patch("frontend.server.bank_rpc.time", SimpleNamespace(time=lambda: clock["now"])):
            with self.assertRaises(BankRPCError) as error:
                await self.rpc().call("list_my_transactions", {}, self.context)
        self.assertEqual(error.exception.code, "bank_authority_expired")
        self.assertFalse(error.exception.possibly_sent)
        self.assertEqual(self.calls(), [])

    async def test_revoke_while_handshake_paused_denies_new_grant(self):
        entered, release = asyncio.Event(), asyncio.Event()
        revoked = False
        checks = []
        def admission():
            checks.append(revoked)
            if revoked:
                raise BankRPCError("authorization_denied")
        context = replace(self.context, admission_check=admission)
        async def paused(request):
            body = json.loads(request.content)
            if body.get("method") == "initialize":
                entered.set()
                await release.wait()
            return self.respond(request)
        rpc = BankRPC(self.config, transport=httpx.MockTransport(paused))
        operation = asyncio.create_task(rpc.call("confirm_simulated_intake", {}, context))
        await asyncio.wait_for(entered.wait(), 2)
        revoked = True
        release.set()
        with self.assertRaises(BankRPCError) as error:
            await operation
        self.assertEqual(error.exception.code, "authorization_denied")
        self.assertFalse(error.exception.possibly_sent)
        self.assertEqual(checks, [False, True])
        self.assertEqual(self.calls(), [])
        self.assertNotIn("admission_check", repr(context))

    async def test_late_success_is_suppressed_after_local_admission_is_revoked(self):
        revoked = False
        def admission():
            if revoked:
                raise BankRPCError("authorization_denied")
        def completed(request, body):
            nonlocal revoked
            revoked = True
            return tool_response(request, body, self.value)
        self.tool_handler = completed
        with self.assertRaises(BankRPCError) as error:
            await self.rpc().call("read_intake_receipt", {}, replace(self.context, admission_check=admission))
        self.assertEqual(error.exception.code, "authorization_denied")
        self.assertTrue(error.exception.possibly_sent)

    async def test_selectors_and_noncanonical_json_are_rejected_before_transport(self):
        for args in [{"customer_id": "other"}, {"conversation_id": "other"}, {"amount": float("nan")},
                     {"selection_handle": object()}, {"date": "\ud800"}]:
            with self.subTest(args_type=list(args)), self.assertRaises(BankRPCError) as error:
                await self.rpc().call("list_my_transactions", args, self.context)
            self.assertEqual(error.exception.code, "invalid_arguments")
        self.assertEqual(self.requests, [])

    async def test_structured_busy_is_definitive_but_http429_remains_uncertain(self):
        self.tool_handler = lambda request, body: tool_response(request, body, {"error": "server_busy"}, error=True)
        with self.assertRaises(BankRPCError) as busy:
            await self.rpc().call("prepare_unrecognized_charge", {}, self.context)
        self.assertEqual(busy.exception.code, "server_busy")
        self.assertFalse(busy.exception.possibly_sent)
        self.requests.clear()
        self.tool_handler = lambda request, body: httpx.Response(429, json={"private": "no retry proof"})
        with self.assertRaises(BankRPCError) as uncertain:
            await self.rpc().call("confirm_simulated_intake", {}, self.context)
        self.assertEqual(uncertain.exception.code, "bank_http_error")
        self.assertTrue(uncertain.exception.possibly_sent)
        self.assertEqual(len(self.calls()), 1)

    async def test_mcp_business_failure_is_not_success_and_unknown_error_is_redacted(self):
        for code, expected in [("risk_data_unavailable", "risk_data_unavailable"),
                               ("private credential/body leaked upstream", "service_unavailable")]:
            with self.subTest(code=expected):
                self.tool_handler = lambda request, body: tool_response(request, body, {"error": code}, error=True)
                with self.assertRaises(BankRPCError) as error:
                    await self.rpc().call("confirm_simulated_intake", {}, self.context)
                self.assertEqual(str(error.exception), expected)
                self.assertTrue(error.exception.possibly_sent)

    async def test_lost_response_is_not_retried_and_delivery_flag_is_phase_bound(self):
        def fail(request, _):
            raise httpx.ReadError("sensitive upstream exception", request=request)
        self.tool_handler = fail
        with self.assertRaises(BankRPCError) as lost:
            await self.rpc().call("confirm_simulated_intake", {}, self.context)
        self.assertEqual(str(lost.exception), "bank_unreachable")
        self.assertTrue(lost.exception.possibly_sent)
        self.assertEqual(len(self.calls()), 1)
        self.requests.clear()
        self.init_handler = fail
        with self.assertRaises(BankRPCError) as before:
            await self.rpc().call("confirm_simulated_intake", {}, self.context)
        self.assertFalse(before.exception.possibly_sent)
        self.assertEqual(self.calls(), [])

    async def test_timeout_is_fixed_and_does_not_repeat_dispatch(self):
        def timeout(request, _):
            raise httpx.ReadTimeout("private details", request=request)
        self.tool_handler = timeout
        with self.assertRaises(BankRPCError) as error:
            await self.rpc().call("confirm_simulated_intake", {}, self.context)
        self.assertEqual(str(error.exception), "bank_timeout")
        self.assertTrue(error.exception.possibly_sent)
        self.assertEqual(len(self.calls()), 1)

    async def test_wrong_rpc_id_or_rpc_error_is_unverified(self):
        for value in [{"jsonrpc": "2.0", "id": "another", "result": {}},
                      {"jsonrpc": "2.0", "id": "another", "error": {"code": -32000, "message": "secret"}}]:
            with self.subTest(kind=list(value)):
                self.tool_handler = lambda request, body: httpx.Response(200, json=value)
                with self.assertRaises(BankRPCError) as error:
                    await self.rpc().call("read_intake_receipt", {}, self.context)
                self.assertEqual(str(error.exception), "bank_invalid_response")
                self.assertTrue(error.exception.possibly_sent)

    async def test_duplicate_keys_and_conflicting_evidence_are_rejected(self):
        def duplicates(request, body):
            raw = '{"jsonrpc":"2.0","id":' + json.dumps(body["id"]) + ',"result":{},"result":{}}'
            return httpx.Response(200, content=raw, headers={"content-type": "application/json"})
        def conflict(request, body):
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {
                "structuredContent": {"verified": True}, "content": [{"type": "text", "text": '{"verified":1}'}]}})
        for handler in [duplicates, conflict]:
            with self.subTest(handler=handler.__name__):
                self.tool_handler = handler
                with self.assertRaises(BankRPCError) as error:
                    await self.rpc().call("read_verified_handoff", {}, self.context)
                self.assertEqual(error.exception.code, "bank_invalid_response")

    async def test_missing_structured_content_or_error_flag_is_not_truth(self):
        for result in [{"content": [{"type": "text", "text": '{"state":"created"}'}]},
                       {"structuredContent": {"state": "created"}, "content": [], "isError": False},
                       {"structuredContent": {"error": "action_unverified"},
                        "content": [{"type": "text", "text": '{"error":"action_unverified"}'}], "isError": False}]:
            with self.subTest(fields=list(result)):
                self.tool_handler = lambda request, body: httpx.Response(200,
                    json={"jsonrpc": "2.0", "id": body["id"], "result": result})
                with self.assertRaises(BankRPCError) as error:
                    await self.rpc().call("read_intake_receipt", {}, self.context)
                self.assertEqual(error.exception.code, "bank_invalid_response")

    async def test_tasks_resources_and_extra_wrapper_fields_are_not_accepted_evidence(self):
        for additions in ({"task": {"status": "working"}}, {"_meta": {"approval": "pending"}},
                          {"resources": [{"uri": "private:record"}]}):
            def response(request, body):
                result = {"structuredContent": self.value,
                    "content": [{"type": "text", "text": json.dumps(self.value)}], **additions}
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})
            self.tool_handler = response
            with self.assertRaises(BankRPCError) as error:
                await self.rpc().call("read_intake_receipt", {}, self.context)
            self.assertEqual(error.exception.code, "bank_invalid_response")

    async def test_changed_protocol_or_stateful_server_stops_before_tool(self):
        for version, headers in [("2024-11-05", {}), (PROTOCOL_VERSION, {"MCP-Session-Id": "foreign-session"})]:
            with self.subTest(version=version, stateful=bool(headers)):
                self.requests.clear()
                self.init_handler = lambda request, body: httpx.Response(200, headers=headers,
                    json={"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": version,
                        "capabilities": {"tools": {}}, "serverInfo": {"name": "banking-mcp", "version": "1"}}})
                with self.assertRaises(BankRPCError) as error:
                    await self.rpc().call("list_my_transactions", {}, self.context)
                self.assertFalse(error.exception.possibly_sent)
                self.assertEqual(self.calls(), [])

    async def test_stream_or_redirect_is_not_an_accepted_json_result(self):
        for status, headers in [(200, {"content-type": "text/event-stream"}),
                                (307, {"location": "http://flujo:4200/v1/chat/completions"})]:
            with self.subTest(status=status):
                self.requests.clear()
                self.tool_handler = lambda request, body: httpx.Response(status, headers=headers, content=b"secret")
                with self.assertRaises(BankRPCError) as error:
                    await self.rpc().call("list_my_transactions", {}, self.context)
                self.assertTrue(error.exception.possibly_sent)
                self.assertEqual(len(self.calls()), 1)

    async def test_oversized_arguments_and_response_are_bounded(self):
        with self.assertRaises(BankRPCError) as request_error:
            await self.rpc().call("list_my_transactions", {"large": "a" * 65536}, self.context)
        self.assertEqual(request_error.exception.code, "invalid_arguments")
        self.assertFalse(request_error.exception.possibly_sent)
        self.assertEqual(self.calls(), [])
        self.tool_handler = lambda request, body: httpx.Response(200, content=b"a" * (4 * 1024 * 1024 + 1),
                                                               headers={"content-type": "application/json"})
        with self.assertRaises(BankRPCError) as response_error:
            await self.rpc().call("list_my_transactions", {}, self.context)
        self.assertEqual(response_error.exception.code, "bank_invalid_response")
        self.assertTrue(response_error.exception.possibly_sent)

    async def test_revocation_has_its_own_type_scope_and_strict_ack(self):
        rpc = self.rpc()
        await rpc.revoke(self.context)
        await rpc.revoke(self.context)
        self.assertEqual([request.url.path for request, _ in self.requests], ["/internal/revoke"] * 2)
        decoded = []
        for request, body in self.requests:
            self.assertEqual(set(body), {"assertion"})
            self.assertEqual(jwt.get_unverified_header(body["assertion"])["typ"], "bank-revoke+jwt")
            claims = self.claims(body["assertion"])
            decoded.append(claims)
            self.assertEqual((claims["tool"], claims["scope"]), ("revoke_session", ["bank:revoke"]))
            self.assertEqual(claims["args_sha256"], hashlib.sha256(rfc8785.dumps({})).hexdigest())
            self.assertEqual(claims["session_id"], self.context.session_id)
            self.assertEqual(claims["ledger_generation"], GENERATED_LEDGER_GENERATION)
            self.assertNotIn("X-Flujo-User-Assertion", request.headers)
        self.assertNotEqual(decoded[0]["jti"], decoded[1]["jti"])
        bad = BankRPC(self.config, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"revoked": 1})))
        with self.assertRaises(BankRPCError) as error:
            await bad.revoke(self.context)
        self.assertEqual(error.exception.code, "bank_invalid_response")
        self.assertTrue(error.exception.possibly_sent)

    def test_configuration_cannot_be_a_language_signer_or_external_http_origin(self):
        for changes in [{"audience": "flujo-banking-ingress"}, {"base_url": "http://flujo:4200"},
                        {"base_url": "http://external.example"}, {"base_url": "https://bank.example/mcp"},
                        {"base_url": "https://bank.example\n"}, {"base_url": "https://bank.example:99999"},
                        {"base_url": "https://user:secret@bank.example"}, {"signing_key_file": "relative.pem"},
                        {"service_token": "x" * 32 + "\x1b"}, {"execution_token": "language-token"},
                        {"ca_file": "relative-ca.pem"}, {"ca_file": ""},
                        {"base_url": "http://banking-mcp:8000"}]:
            with self.subTest(fields=list(changes)), self.assertRaises(ValueError) as error:
                BankRPC({**self.config, **changes})
            self.assertEqual(str(error.exception), "invalid_bank_configuration")

    def test_explicit_tls_trust_requires_hostname_and_certificate_verification(self):
        rpc = self.rpc()
        self.assertEqual(rpc._tls.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(rpc._tls.check_hostname)
        self.assertTrue(rpc._tls.get_ca_certs(binary_form=True))
        self.assertEqual(rpc.authority_identity["endpoint"], "https://banking-mcp:8000")
        self.assertEqual(rpc.authority_identity["tls_ca_sha256"],
            hashlib.sha256(Path(self.config["ca_file"]).read_bytes()).hexdigest())
        self.assertEqual(rpc.authority_identity["signer_sha256"], hashlib.sha256(
            self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).hexdigest())
        invalid = Path(self.directory.name) / "invalid-ca.pem"
        invalid.write_text("This is generated test text, not a certificate", encoding="utf-8")
        with self.assertRaises(ValueError):
            BankRPC({**self.config, "ca_file": str(invalid)})

    def test_context_rejects_fabricated_revision_or_noncanonical_operation_id(self):
        for changes in [{"operation_id": "worker-run-invented"}, {"host_revision": "flow-language-name"},
                        {"host_revision": "A" * 40}, {"session_expires": True}, {"subject": "a\x00"},
                        {"ledger_generation": ""}, {"ledger_generation": "D" * 64},
                        {"ledger_generation": "d" * 63}]:
            with self.subTest(fields=list(changes)), self.assertRaises(ValueError):
                replace(self.context, **changes)
