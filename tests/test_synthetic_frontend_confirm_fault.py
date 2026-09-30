"""Pure fake-transport/journal tests; no actual confirmation or service is run."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import httpx

from scripts.synthetic_integration.frontend_confirm_fault import (
    ConfirmCommitProof, ConfirmDropTransport, ConfirmScope, FileConfirmJournal,
)
from scripts.synthetic_integration.frontend_fault import (
    FaultVerificationError, HostPrepareIntent, PrepareBinding, canonical_digest,
)
from tests.test_synthetic_frontend_fault import ACTION_ID, CONVERSATION, FACTS, REQUEST_ID, Harness, fixture_scope


HANDLE = "a" * 43


def confirm_scope():
    fixture = fixture_scope()
    original = HostPrepareIntent(fixture.digest,
        PrepareBinding(REQUEST_ID, CONVERSATION, fixture.transaction_id, fixture.snapshot),
        ACTION_ID, 2, fixture.frontend_session_exp)
    return ConfirmScope(fixture, original, "txn_" + "a" * 24, hashlib.sha256(HANDLE.encode()).hexdigest())


def receipt_result(scope):
    return {"state": "intake_verified", "receipt": {"id": "CMP-SBX-abcdefgh", "kind": "simulated_intake",
        "simulated": True, "status": "received", "snapshot": scope.fixture.snapshot,
        "created_at": "2026-09-30T12:00:00Z", "transaction": dict(FACTS)}}


def confirm_request(scope, *, assertion="fresh-confirm-assertion", **changes):
    return httpx.Request("POST", scope.fixture.worker_origin + "/v1/banking/action",
        headers={"Authorization": "Bearer generated-worker-token", "X-Flujo-User-Assertion": assertion},
        content=json.dumps({"operation": "confirm", "conversationId": CONVERSATION,
                            "pendingHandle": HANDLE, "confirmed": True, **changes}, indent=2).encode())


class ConfirmHarness(Harness):
    def __init__(self):
        self.confirm_scope = confirm_scope()
        super().__init__(self.confirm_scope.fixture)
        self.result = receipt_result(self.confirm_scope)
        self.proof_override = "default"

    async def confirmation_intent(self, original, handle, target):
        self.events.append("confirm-intent")
        if handle != HANDLE or target != self.confirm_scope.target_reference:
            raise AssertionError("fake fixture mismatch")
        return replace(original, revision=3, **self.intent_change)

    async def confirmation_commit(self, scope, handle, result):
        self.events.append("confirm-commit")
        if self.proof_override != "default":
            return self.proof_override
        return replace(ConfirmCommitProof(scope.digest, scope.original_intent.binding,
            hashlib.sha256(handle.encode()).hexdigest(), canonical_digest(result), "b" * 64,
            result["receipt"]["id"], "c" * 64, "d" * 64, canonical_digest(result["receipt"])), **self.proof_change)

    def confirm_transport(self, *, consumed=None, recorder=None):
        return ConfirmDropTransport(self.confirm_scope, inner_factory=self.factory,
            verify_identity=self.identity, resolve_confirmation_intent=self.confirmation_intent,
            verify_confirmation_commit=self.confirmation_commit, record_consumed=recorder or self.record,
            consumed=consumed)


class ConfirmDropTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_response_shape_is_withheld_after_proof_without_reconfirm(self):
        harness = ConfirmHarness()
        transport = harness.confirm_transport()
        original = confirm_request(harness.confirm_scope)
        expected_bytes, expected_headers = original.content, tuple(original.headers.raw)
        with self.assertRaises(httpx.ReadError):
            await transport.handle_async_request(original)
        self.assertEqual(harness.requests, [(original, expected_bytes, expected_headers)])
        self.assertEqual(harness.events, ["identity", "confirm-intent", "forward", "inner-close",
                                        "confirm-commit", "confirm-intent", "record"])
        self.assertEqual(len(harness.markers), 1)
        self.assertIs(transport.consumed, harness.markers[0])
        await transport.aclose()  # Host closes its client before inline receipt recovery.
        receipt = httpx.Request("POST", harness.scope.worker_origin + "/v1/banking/action",
            headers={"X-Flujo-User-Assertion": "new-receipt-assertion"},
            json={"operation": "receipt", "conversationId": CONVERSATION, "pendingHandle": HANDLE})
        response = await transport.handle_async_request(receipt)
        self.assertEqual(response.json(), harness.result)
        self.assertEqual(len(harness.requests), 2)
        self.assertEqual(harness.requests[1][0].headers["X-Flujo-User-Assertion"], "new-receipt-assertion")
        with self.assertRaisesRegex(FaultVerificationError, "must not be repeated"):
            await transport.handle_async_request(confirm_request(harness.confirm_scope))
        self.assertEqual(len(harness.requests), 2)
        self.assertTrue(all(inner.closed == 1 for inner in harness.inners))

    async def test_nonmatching_confirm_and_other_operations_are_unmodified(self):
        for changes in ({"operation": "receipt"}, {"pendingHandle": "b" * 43},
                        {"confirmed": False}, {"extra": "not-a-strict-confirm"}):
            with self.subTest(changes=changes):
                harness = ConfirmHarness()
                original = confirm_request(harness.confirm_scope, **changes)
                response = await harness.confirm_transport().handle_async_request(original)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(harness.events, ["forward", "inner-close"])
                self.assertEqual(harness.markers, [])

    async def test_wrong_origin_conversation_identity_or_host_intent_prevents_write(self):
        harness = ConfirmHarness()
        with self.assertRaises(FaultVerificationError):
            await harness.confirm_transport().handle_async_request(httpx.Request("POST", "http://other.invalid/v1/banking/action"))
        with self.assertRaises(FaultVerificationError):
            await harness.confirm_transport().handle_async_request(confirm_request(harness.confirm_scope, conversationId=ACTION_ID))
        self.assertEqual(harness.requests, [])
        harness.identity_change["subject"] = "another-subject"
        with self.assertRaises(FaultVerificationError):
            await harness.confirm_transport().handle_async_request(confirm_request(harness.confirm_scope))
        harness.identity_change.clear()
        harness.intent_change["action_id"] = "44444444-4444-4444-8444-444444444444"
        with self.assertRaises(FaultVerificationError):
            await harness.confirm_transport().handle_async_request(confirm_request(harness.confirm_scope))
        self.assertEqual(harness.requests, [])

    async def test_unadmitted_429_is_not_rewritten_or_consumed(self):
        harness = ConfirmHarness()
        harness.status = 429
        transport = harness.confirm_transport()
        response = await transport.handle_async_request(confirm_request(harness.confirm_scope))
        self.assertEqual(response.status_code, 429)
        self.assertEqual(harness.markers, [])
        self.assertIsNone(transport.consumed)
        self.assertNotIn("confirm-commit", harness.events)

    async def test_canned_success_without_exact_actual_case_and_receipt_proof_fails(self):
        for override, changes in ((None, {}), (False, {}), ("default", {"receipt_sha256": "0" * 64}),
                                  ("default", {"pending_handle_sha256": "0" * 64}),
                                  ("default", {"case_id": "CMP-SBX-ijklmnop"}),
                                  ("default", {"case_row_digest": "not-a-row-proof"})):
            with self.subTest(override=override, changes=changes):
                harness = ConfirmHarness()
                harness.proof_override, harness.proof_change = override, changes
                with self.assertRaises(FaultVerificationError):
                    await harness.confirm_transport().handle_async_request(confirm_request(harness.confirm_scope))
                self.assertEqual(len(harness.requests), 1)
                self.assertEqual(harness.markers, [])

    async def test_wrong_receipt_or_policy_handoff_never_consumes_confirm_fault(self):
        for mutate in (lambda r: r["receipt"].update(snapshot="another-build"),
                       lambda r: r["receipt"]["transaction"].update(amount="151.00"),
                       lambda r: r.update(state="handoff_verified")):
            harness = ConfirmHarness()
            mutate(harness.result)
            with self.assertRaises(FaultVerificationError):
                await harness.confirm_transport().handle_async_request(confirm_request(harness.confirm_scope))
            self.assertEqual(harness.markers, [])
            self.assertNotIn("confirm-commit", harness.events)

    async def test_postcommit_intent_change_and_failed_record_are_not_transport_faults(self):
        harness = ConfirmHarness()
        async def racing(scope, handle, result):
            proof = await harness.confirmation_commit(scope, handle, result)
            harness.intent_change["action_id"] = "44444444-4444-4444-8444-444444444444"
            return proof
        transport = ConfirmDropTransport(harness.confirm_scope, inner_factory=harness.factory,
            verify_identity=harness.identity, resolve_confirmation_intent=harness.confirmation_intent,
            verify_confirmation_commit=racing, record_consumed=harness.record)
        with self.assertRaises(FaultVerificationError):
            await transport.handle_async_request(confirm_request(harness.confirm_scope))
        self.assertEqual(harness.markers, [])
        harness = ConfirmHarness()
        harness.recorder_ok = False
        transport = harness.confirm_transport()
        with self.assertRaises(FaultVerificationError):
            await transport.handle_async_request(confirm_request(harness.confirm_scope))
        self.assertIsNone(transport.consumed)

    async def test_durable_confirm_marker_has_no_capability_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            harness = ConfirmHarness()
            fixture = harness.scope
            (root / "synthetic_provenance.json").write_text(json.dumps({"kind": "team_synthetic_fixture",
                "build_id": fixture.snapshot, "source_fingerprint": fixture.source_fingerprint}), encoding="utf-8")
            path = root / "confirm-consumed.json"
            journal = FileConfirmJournal(harness.confirm_scope, fixture_root=root, path=path)
            transport = harness.confirm_transport(recorder=journal.record)
            with self.assertRaises(httpx.ReadError):
                await transport.handle_async_request(confirm_request(harness.confirm_scope))
            content = path.read_bytes()
            self.assertNotIn(HANDLE.encode(), content)
            self.assertNotIn(b"fresh-confirm-assertion", content)
            self.assertNotIn(b"generated-worker-token", content)
            self.assertNotIn(b"Cuenta Ahorro", content)
            reloaded = FileConfirmJournal(harness.confirm_scope, fixture_root=root, path=path)
            marker = reloaded.load()
            self.assertEqual(marker, transport.consumed)
            self.assertTrue(await reloaded.record(marker))
            self.assertEqual(path.read_bytes(), content)
            restarted = harness.confirm_transport(consumed=marker, recorder=reloaded.record)
            with self.assertRaisesRegex(FaultVerificationError, "must not be repeated"):
                await restarted.handle_async_request(confirm_request(harness.confirm_scope))
            self.assertEqual(len(harness.requests), 1)
            with self.assertRaises(FaultVerificationError):
                harness.confirm_transport(consumed=replace(marker, digest="0" * 64))
            path.write_text('{"not":"confirmed-proof"}', encoding="utf-8")
            with self.assertRaises(FaultVerificationError):
                reloaded.load()
            self.assertEqual(list(root.glob(".confirm-drop-*")), [])
