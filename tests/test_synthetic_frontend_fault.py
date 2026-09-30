"""Pure transport/temporary-journal tests, never joint FLUJO/MCP commit evidence.

Fake transports return authored Response objects. No application, model, service,
socket, JWT bypass or live fixture is started by these tests.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import httpx

from scripts.synthetic_integration.frontend_fault import (
    ConsumedDrop, FaultVerificationError, FileConsumedJournal, FixtureScope,
    HostPrepareIntent, PrepareBinding, PrepareCommitProof, PrepareDropTransport,
    VerifiedIdentity, canonical_digest,
)


REQUEST_ID = "11111111-1111-4111-8111-111111111111"
CONVERSATION = "22222222-2222-4222-8222-222222222222"
ACTION_ID = "33333333-3333-4333-8333-333333333333"
FACTS = {"transaction_reference": "txn_" + "a" * 12,
         "transaction_date": "2026-09-29T12:00:00", "process_date": "2026-09-29",
         "amount": "150.00", "currency": "COP", "status": "Approved", "merchant": None,
         "transaction_type": "Deposit", "channel": "App", "product": "Cuenta Ahorro"}


def fixture_scope(outcome="pending_confirmation"):
    return FixtureScope(fixture_id="generated-fault-test", source_fingerprint="b" * 64,
                        profile_id="generated-profile", worker_origin="http://worker.invalid:3000",
                        issuer="https://frontend.invalid", subject="generated-subject",
                        frontend_session_id="generated-session", frontend_session_exp=2000000000,
                        frontend_model="generated-model", frontend_owner="c" * 64,
                        bank_deployment_id="generated-deployment", bank_session_id="d" * 64,
                        customer_id="generated-customer", transaction_id="generated-transaction",
                        snapshot="synthetic-build", facts_sha256=canonical_digest(FACTS),
                        ledger_generation="e" * 64, expected_outcome=outcome)


def prepare_result(scope):
    result = {"state": scope.expected_outcome, "pending_handle": "a" * 43, "snapshot": scope.snapshot,
              "action": "simulated_intake", "decision": "intake", "reason": None, "transaction": dict(FACTS)}
    if scope.expected_outcome == "handoff_verified":
        packet = {"schema": "banking-sandbox-handoff/v1", "transaction": dict(FACTS),
                  "transaction_provenance": {"source": "owned_serving_snapshot", "snapshot": scope.snapshot,
                                             "as_of": "2026-09-30T12:00:00Z"},
                  "reason": "missing_evidence", "unanswered_questions": [], "human_responded": False}
        result.update(decision="handoff", reason="missing_evidence", handoff={
            "id": "HOF-abcdefgh", "reason": "missing_evidence", "snapshot": scope.snapshot,
            "created_at": "2026-09-30T12:00:00Z", "human_responded": False, "facts": dict(FACTS),
            "transaction_currentness": "same_snapshot", "packet": packet})
    return result


def request(scope, *, assertion="first-signed-token", **body_changes):
    body = {"operation": "prepare", "conversationId": CONVERSATION, "requestId": REQUEST_ID,
            "transactionId": scope.transaction_id, "snapshot": scope.snapshot, **body_changes}
    # Deliberate whitespace makes unchanged byte forwarding observable.
    return httpx.Request("POST", scope.worker_origin + "/v1/banking/action",
                         headers={"Authorization": "Bearer generated-worker-token",
                                  "X-Flujo-User-Assertion": assertion, "X-Sentinel": "keep-exact"},
                         content=json.dumps(body, indent=2).encode())


class FakeInner(httpx.AsyncBaseTransport):
    def __init__(self, harness):
        self.harness = harness
        self.closed = 0

    async def handle_async_request(self, original):
        self.harness.events.append("forward")
        self.harness.requests.append((original, await original.aread(), tuple(original.headers.raw)))
        if self.harness.upstream_error is not None:
            raise self.harness.upstream_error
        return httpx.Response(self.harness.status, json=self.harness.result,
                              headers={"X-Upstream-Sentinel": "actual-fake-response"}, request=original)

    async def aclose(self):
        self.closed += 1
        self.harness.events.append("inner-close")


class Harness:
    def __init__(self, scope=None):
        self.scope = scope or fixture_scope()
        self.result = prepare_result(self.scope)
        self.status = 200
        self.events = []
        self.requests = []
        self.inners = []
        self.markers = []
        self.identity_change = {}
        self.intent_change = {}
        self.proof_change = {}
        self.proof_override = "default"
        self.recorder_ok = True
        self.upstream_error = None

    def factory(self):
        inner = FakeInner(self)
        self.inners.append(inner)
        return inner

    async def identity(self, headers):
        self.events.append("identity")
        return replace(VerifiedIdentity(self.scope.issuer, self.scope.subject, self.scope.frontend_session_id,
                                       self.scope.frontend_session_exp, self.scope.frontend_session_exp - 1,
                                       hashlib.sha256(headers["X-Flujo-User-Assertion"].encode()).hexdigest()),
                       **self.identity_change)

    async def intent(self, scope, binding):
        self.events.append("intent")
        return replace(HostPrepareIntent(scope.digest, binding, ACTION_ID, 1, scope.frontend_session_exp),
                       **self.intent_change)

    async def commit(self, scope, binding, result):
        self.events.append("commit")
        if self.proof_override != "default":
            return self.proof_override
        hof = result.get("handoff")
        return replace(PrepareCommitProof(scope.digest, binding, result["pending_handle"],
                       canonical_digest(result), "e" * 64,
                       hof["id"] if hof else None, canonical_digest(hof["packet"]) if hof else None,
                       "f" * 64 if hof else None), **self.proof_change)

    async def record(self, marker):
        self.events.append("record")
        self.markers.append(marker)
        return self.recorder_ok

    def transport(self, *, consumed=None, recorder=None):
        return PrepareDropTransport(self.scope, inner_factory=self.factory, verify_identity=self.identity,
                                    resolve_host_intent=self.intent, verify_commit=self.commit,
                                    record_consumed=recorder or self.record, consumed=consumed)


class PrepareDropTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_pending_success_is_withheld_once_after_verified_record(self):
        harness = Harness()
        transport = harness.transport()
        original = request(harness.scope)
        body, headers = original.content, tuple(original.headers.raw)
        with self.assertRaises(httpx.ReadError):
            await transport.handle_async_request(original)
        self.assertEqual(harness.requests, [(original, body, headers)])
        self.assertEqual(harness.events, ["identity", "intent", "forward", "inner-close", "commit", "intent", "record"])
        self.assertIs(transport.consumed, harness.markers[0])
        self.assertTrue(all(inner.closed == 1 for inner in harness.inners))
        await transport.aclose()  # Simulate host's per-POST client teardown.
        replay = request(harness.scope, assertion="fresh-signed-token")
        response = await transport.handle_async_request(replay)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), harness.result)
        self.assertEqual(response.headers["X-Upstream-Sentinel"], "actual-fake-response")
        self.assertEqual(len(harness.markers), 1)
        self.assertEqual(len(harness.inners), 2)
        self.assertEqual(harness.requests[1][0].headers["X-Flujo-User-Assertion"], "fresh-signed-token")

    async def test_fixed_policy_handoff_requires_pending_and_packet_commit_proof(self):
        harness = Harness(fixture_scope("handoff_verified"))
        transport = harness.transport()
        with self.assertRaises(httpx.ReadError):
            await transport.handle_async_request(request(harness.scope))
        proof = transport.consumed.proof
        self.assertEqual(proof.handoff_id, harness.result["handoff"]["id"])
        self.assertEqual(proof.handoff_packet_sha256, canonical_digest(harness.result["handoff"]["packet"]))
        self.assertIsNotNone(proof.handoff_row_digest)

    async def test_nonmatching_requests_are_forwarded_without_fault_observers(self):
        for changes in ({"operation": "confirm"}, {"transactionId": "other-generated-charge"},
                        {"snapshot": "other-build"}, {"extra": "not-the-strict-tuple"}):
            with self.subTest(changes=changes):
                harness = Harness()
                response = await harness.transport().handle_async_request(request(harness.scope, **changes))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(harness.events, ["forward", "inner-close"])
        for method, path in (("GET", "/v1/banking/action"), ("POST", "/v1/chat/completions"),
                             ("POST", "/v1/banking/action?unused=1")):
            harness = Harness()
            original = httpx.Request(method, harness.scope.worker_origin + path, content=b"{}")
            await harness.transport().handle_async_request(original)
            self.assertEqual(harness.events, ["forward", "inner-close"])

    async def test_wrong_origin_is_rejected_before_forwarding(self):
        harness = Harness()
        with self.assertRaises(FaultVerificationError):
            await harness.transport().handle_async_request(httpx.Request("POST", "http://other.invalid/v1/banking/action"))
        self.assertEqual(harness.requests, [])

    async def test_unadmitted_429_and_real_upstream_failure_do_not_consume(self):
        harness = Harness()
        transport = harness.transport()
        harness.status = 429
        response = await transport.handle_async_request(request(harness.scope))
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("commit", harness.events)
        self.assertIsNone(transport.consumed)
        harness.status = 200
        harness.upstream_error = httpx.ReadTimeout("authored upstream timeout")
        with self.assertRaises(httpx.ReadTimeout):
            await transport.handle_async_request(request(harness.scope))
        self.assertEqual(harness.markers, [])
        self.assertTrue(all(inner.closed == 1 for inner in harness.inners))

    async def test_canned_200_false_or_mismatched_commit_cannot_trigger_drop(self):
        for override, changes in ((False, {}), (None, {}), ("default", {"pending_handle": "b" * 43}),
                                  ("default", {"response_sha256": "0" * 64}),
                                  ("default", {"pending_row_digest": "not-a-proof"}),
                                  ("default", {"binding": PrepareBinding(REQUEST_ID, CONVERSATION, "wrong", "wrong")})):
            with self.subTest(override=override, changes=changes):
                harness = Harness()
                harness.proof_override, harness.proof_change = override, changes
                with self.assertRaises(FaultVerificationError):
                    await harness.transport().handle_async_request(request(harness.scope))
                self.assertEqual(len(harness.requests), 1)
                self.assertEqual(harness.markers, [])

    async def test_identity_and_host_intent_are_required_before_upstream(self):
        for field in ("issuer", "subject", "frontend_session_id", "assertion_sha256"):
            harness = Harness()
            harness.identity_change[field] = "wrong"
            with self.assertRaises(FaultVerificationError):
                await harness.transport().handle_async_request(request(harness.scope))
            self.assertEqual(harness.requests, [])
        harness = Harness()
        harness.intent_change["binding"] = PrepareBinding(REQUEST_ID, CONVERSATION, "wrong", "wrong")
        with self.assertRaises(FaultVerificationError):
            await harness.transport().handle_async_request(request(harness.scope))
        self.assertEqual(harness.requests, [])

    async def test_wrong_facts_and_incomplete_handoff_do_not_consume(self):
        mutations = [lambda r: r["transaction"].update(amount="151.00"),
                     lambda r: r["transaction"].update(amount="1E2"),
                     lambda r: r["handoff"]["packet"].update(unanswered_questions=["invented"]),
                     lambda r: r["handoff"]["packet"].update(human_responded=True),
                     lambda r: r["handoff"].update(transaction_provenance=None)]
        for mutation in mutations:
            harness = Harness(fixture_scope("handoff_verified"))
            mutation(harness.result)
            with self.assertRaises(FaultVerificationError):
                await harness.transport().handle_async_request(request(harness.scope))
            self.assertNotIn("commit", harness.events)
            self.assertEqual(harness.markers, [])
        harness = Harness(fixture_scope("handoff_verified"))
        harness.proof_change["handoff_row_digest"] = None
        with self.assertRaises(FaultVerificationError):
            await harness.transport().handle_async_request(request(harness.scope))
        self.assertEqual(harness.markers, [])

    async def test_failed_recorder_or_callback_is_harness_error_not_transport_drop(self):
        harness = Harness()
        harness.recorder_ok = False
        transport = harness.transport()
        with self.assertRaises(FaultVerificationError):
            await transport.handle_async_request(request(harness.scope))
        self.assertIsNone(transport.consumed)
        async def broken(*args):
            raise httpx.ReadTimeout("sensitive callback detail must not leak")
        transport = PrepareDropTransport(harness.scope, inner_factory=harness.factory,
            verify_identity=harness.identity, resolve_host_intent=harness.intent,
            verify_commit=broken, record_consumed=harness.record)
        with self.assertRaisesRegex(FaultVerificationError, "fixture proof callback failed"):
            await transport.handle_async_request(request(harness.scope))

    async def test_concurrent_intent_change_before_consumption_is_rejected(self):
        harness = Harness()
        async def changed_at_commit(scope, binding, result):
            proof = await harness.commit(scope, binding, result)
            harness.intent_change["action_id"] = "44444444-4444-4444-8444-444444444444"
            return proof
        transport = PrepareDropTransport(harness.scope, inner_factory=harness.factory,
            verify_identity=harness.identity, resolve_host_intent=harness.intent,
            verify_commit=changed_at_commit, record_consumed=harness.record)
        with self.assertRaisesRegex(FaultVerificationError, "intent changed"):
            await transport.handle_async_request(request(harness.scope))
        self.assertEqual(harness.markers, [])
        self.assertIsNone(transport.consumed)

    async def test_loaded_consumption_checks_original_identity_and_allows_later_intent(self):
        harness = Harness()
        transport = harness.transport()
        with self.assertRaises(httpx.ReadError):
            await transport.handle_async_request(request(harness.scope))
        marker = transport.consumed
        with self.assertRaises(FaultVerificationError):
            PrepareDropTransport(replace(harness.scope, fixture_id="different"), inner_factory=harness.factory,
                verify_identity=harness.identity, resolve_host_intent=harness.intent,
                verify_commit=harness.commit, record_consumed=harness.record, consumed=marker)
        with self.assertRaises(FaultVerificationError):
            harness.transport(consumed=replace(marker, digest="0" * 64))
        restarted = harness.transport(consumed=marker)
        new_id = "44444444-4444-4444-8444-444444444444"
        # A changed UUID masquerading as the original action is invalid.
        with self.assertRaises(FaultVerificationError):
            await restarted.handle_async_request(request(harness.scope, requestId=new_id))
        harness.intent_change["action_id"] = new_id
        with self.assertRaises(FaultVerificationError):
            await restarted.handle_async_request(request(harness.scope))
        self.assertEqual(len(harness.requests), 1)
        # An actual later reservation has its own action ID and greater revision;
        # it does not re-arm, replace, or extend the first one-shot fault.
        harness.intent_change["revision"] = 3
        response = await restarted.handle_async_request(request(harness.scope, requestId=new_id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(restarted.consumed, marker)
        self.assertEqual(len(harness.markers), 1)


class JournalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.scope = fixture_scope()
        self.provenance = self.root / "synthetic_provenance.json"
        self.provenance.write_text(json.dumps({"kind": "team_synthetic_fixture", "build_id": self.scope.snapshot,
                                              "source_fingerprint": self.scope.source_fingerprint}), encoding="utf-8")
        self.path = self.root / "prepare-consumed.json"

    async def test_atomic_record_restart_and_fresh_assertion_pass_through(self):
        harness = Harness(self.scope)
        journal = FileConsumedJournal(self.scope, fixture_root=self.root, path=self.path)
        self.assertIsNone(journal.load())
        transport = harness.transport(recorder=journal.record)
        with self.assertRaises(httpx.ReadError):
            await transport.handle_async_request(request(self.scope))
        before = self.path.read_bytes()
        self.assertNotIn(b"signed-token", before)
        self.assertNotIn(b"Authorization", before)
        self.assertNotIn(b"Cuenta Ahorro", before)
        self.assertNotIn(harness.result["pending_handle"].encode(), before)
        self.assertEqual(transport.consumed.proof.pending_handle_sha256,
                         hashlib.sha256(harness.result["pending_handle"].encode()).hexdigest())
        reloaded = FileConsumedJournal(self.scope, fixture_root=self.root, path=self.path)
        marker = reloaded.load()
        self.assertIsInstance(marker, ConsumedDrop)
        self.assertEqual(marker, transport.consumed)
        self.assertTrue(await reloaded.record(marker))
        self.assertEqual(self.path.read_bytes(), before)
        restarted = harness.transport(consumed=marker, recorder=reloaded.record)
        response = await restarted.handle_async_request(request(self.scope, assertion="new-real-verifier-input"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(harness.requests), 2)
        self.assertEqual(list(self.root.glob(".prepare-drop-*")), [])

    async def test_wrong_provenance_path_scope_and_corruption_fail_closed(self):
        with self.assertRaises(FaultVerificationError):
            FileConsumedJournal(self.scope, fixture_root=self.root, path=self.root.parent / "outside.json")
        self.provenance.write_text('{"kind":"organizer-snapshot"}', encoding="utf-8")
        with self.assertRaises(FaultVerificationError):
            FileConsumedJournal(self.scope, fixture_root=self.root, path=self.path)
        self.provenance.write_text(json.dumps({"kind": "team_synthetic_fixture", "build_id": self.scope.snapshot,
                                              "source_fingerprint": self.scope.source_fingerprint}), encoding="utf-8")
        journal = FileConsumedJournal(self.scope, fixture_root=self.root, path=self.path)
        self.path.write_text('{"unexpected":"not-consumed-proof"}', encoding="utf-8")
        with self.assertRaises(FaultVerificationError):
            journal.load()
        self.assertEqual(self.path.read_text(), '{"unexpected":"not-consumed-proof"}')
