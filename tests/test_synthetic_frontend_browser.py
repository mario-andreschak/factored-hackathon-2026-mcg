"""Pure injected-page controls. No browser, server, socket or model is used."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from scripts.synthetic_integration.frontend_browser import (
    BrowserScope, COPY, FrontendBrowserProbe, OwnedSelectionTruth,
    PendingTruth, ReceiptTruth, digest,
)
from scripts.synthetic_integration.frontend_driver import AttestedPhaseEvidence, DriverError, GeneratedFixture


ORIGIN = "http://127.0.0.1:8800"
REFERENCE = "txn_" + "a" * 24
HANDLE = "capability_" + "h" * 32
SERVER_UUID = "11111111-1111-4111-8111-111111111111"
BROWSER_UUID = "22222222-2222-4222-8222-222222222222"
TOKEN = "ephemeral-signed-fixture-cookie"
CODE = "ephemeral-access-code"
REVISION, BUILD_SHA = "f" * 40, "b" * 64
FIXTURE = GeneratedFixture("generated-1", "fixture-1", "a" * 16, "colombia", True)
ATTESTED = AttestedPhaseEvidence("generated-1", "c" * 64, "fixture-1", "a" * 16,
    "e" * 64, 1790000000, "synthetic:present-v1:" + "c" * 64, "d" * 64)
SELECTED = {"reference": REFERENCE, "amount": 42.0, "currency": "COP", "status": "Approved",
    "merchant": "Tienda Ficticia", "occurred_at": "2026-09-20T12:00:00Z", "process_date": "2026-09-20",
    "type": "Compra", "channel": "Card"}
FACTS = {"transaction_reference": "txn_" + "b" * 12, "transaction_date": SELECTED["occurred_at"],
    "process_date": SELECTED["process_date"], "amount": "42.00", "currency": "COP", "status": "Approved",
    "merchant": SELECTED["merchant"], "transaction_type": "Compra", "channel": "Card", "product": "Tarjeta Crédito"}
IDENTITY = {"authenticated": True, "auth_mode": "demo", "profile": {"id": "colombia"}}
OVERVIEW = {"profile": {"id": "colombia"}, "metadata": {"build_id": "fixture-1",
    "source_fingerprint": "a" * 16, "dataset": "organizer-snapshot"}, "transactions": [SELECTED]}
RECEIPT = {"id": "CMP-SBX-abcdefgh", "kind": "simulated_intake", "simulated": True,
    "status": "received", "snapshot": "fixture-1", "created_at": "2026-09-20T12:01:00Z", "transaction": FACTS}


def pending(**changes):
    return {"state": "pending_confirmation", "request_id": SERVER_UUID, "pending_handle": HANDLE,
        "target_reference": REFERENCE, "snapshot": "fixture-1", "transaction": deepcopy(FACTS), **changes}


def terminal(**changes):
    # Exact shipped confirm shape: no wire UUID, top snapshot or top transaction.
    return {"state": "intake_verified", "pending_handle": HANDLE,
            "target_reference": REFERENCE, "receipt": deepcopy(RECEIPT), **changes}


class FakeRequest:
    def __init__(self, method, path, body, token):
        self.method, self.url, self.post_data_json = method, ORIGIN + path, deepcopy(body)
        self.token = token

    async def all_headers(self):
        return {"cookie": "flujo_bank_session=" + self.token}


class FakeResponse:
    def __init__(self, request, body):
        self.request, self.url, self.status, self.body = request, request.url, 200, deepcopy(body)

    async def json(self):
        return deepcopy(self.body)


class Expectation:
    def __init__(self, page, kind, predicate):
        self.page, self.kind, self.predicate = page, kind, predicate
        self.value = asyncio.get_running_loop().create_future()

    async def __aenter__(self):
        self.page.active[self.kind].append(self)
        return self

    async def __aexit__(self, *args):
        self.page.active[self.kind].remove(self)
        if not self.value.done():
            raise AssertionError("Pure fake did not observe expected " + self.kind)


class FakeContext:
    def __init__(self):
        self.token = None

    async def cookies(self, origins):
        assert origins == [ORIGIN]
        return [] if self.token is None else [{"name": "flujo_bank_session", "value": self.token}]


class FakeLocator:
    def __init__(self, page, key):
        self.page, self.key = page, key

    def filter(self, **kwargs):
        return self

    def get_by_role(self, role, **kwargs):
        return self.page.get_by_role(role, **kwargs)

    def locator(self, value):
        return self.page.locator(value)

    async def count(self):
        if self.key == "#login-code":
            return int(self.page.login_visible)
        return 1

    async def click(self):
        self.page.clicks.append(self.key)
        if self.key == "Entrar a mi banca":
            self.page.context.token, self.page.login_visible = TOKEN, False
            self.page.emit("POST", "/api/auth/login", {"profile": "colombia", "code": self.page.code}, IDENTITY)
            self.page.emit("GET", "/api/overview", None, self.page.overview)
        elif self.key == "Revisar este cargo":
            self.page.emit("GET", "/api/action/status", None, self.page.state)
        elif self.key == "Enviar mensaje":
            self.page.emit("POST", "/api/chat/messages", {"message": self.page.message,
                "transaction_reference": REFERENCE}, {"status": "completed", "mode": "flujo", "reply": "Fixture"})
        elif self.key in {COPY[lang]["prepare"] for lang in COPY}:
            body = {"transaction_reference": REFERENCE, "request_id": BROWSER_UUID, "language": self.page.language}
            self.page.state = deepcopy(self.page.prepare_response)
            self.page.emit("POST", "/api/action/prepare", body, self.page.state)
        elif self.key == "confirm":
            # Both request and response observers must exist before any consent click.
            assert self.page.active["request"] and self.page.active["response"]
            body = {"pending_handle": HANDLE, "transaction_reference": REFERENCE,
                    "confirmed": True, "language": self.page.language, **self.page.confirm_body_changes}
            self.page.state = deepcopy(self.page.confirm_response)
            self.page.emit("POST", "/api/action/confirm", body, self.page.state)
        elif self.key in {COPY[lang]["status"] for lang in COPY}:
            self.page.emit("GET", "/api/action/status", None, self.page.state)
        elif self.key in {COPY[lang]["reveal"] for lang in COPY}:
            self.page.amount_visible = True

    async def fill(self, value):
        if self.key == "Código de acceso":
            self.page.code = value
        elif self.key == "Mensaje para el asistente":
            self.page.message = value

    async def select_option(self, value):
        self.page.language = value
        self.page.emit("GET", "/api/action/status", None, self.page.state)

    async def wait_for(self, *, state):
        self.page.waits.append((self.key, state))
        if self.key == "confirm":
            assert (state == "visible") == (self.page.state["state"] == "pending_confirmation")

    async def is_enabled(self):
        return self.page.amount_visible

    async def get_attribute(self, name):
        assert name == "aria-describedby"
        return "saved-charge-summary"

    async def inner_text(self):
        if self.key == '[id="saved-charge-summary"]':
            return self.page.summary if self.page.summary is not None else self.page.evidence_text()
        return self.page.evidence_text()

    async def screenshot(self, *, path):
        data = b"\x89PNG\r\n\x1a\n" + self.key.encode()
        Path(path).write_bytes(data)
        self.page.screenshot_paths.append(path)
        return data


class FakePage:
    def __init__(self, context):
        self.context, self.url, self.language = context, ORIGIN + "/", "es"
        self.listeners, self.active = [], {"request": [], "response": []}
        self.requests, self.clicks, self.waits, self.screenshot_paths = [], [], [], []
        self.code, self.message, self.summary = None, None, None
        self.login_visible, self.amount_visible = True, False
        self.state, self.overview = {"state": "none"}, deepcopy(OVERVIEW)
        self.prepare_response, self.confirm_response, self.confirm_body_changes = pending(), terminal(), {}
        self.response_request_changes = {}

    def on(self, kind, listener):
        assert kind == "request"
        self.listeners.append(listener)

    def remove_listener(self, kind, listener):
        self.listeners.remove(listener)

    def expect_request(self, predicate):
        return Expectation(self, "request", predicate)

    def expect_response(self, predicate):
        return Expectation(self, "response", predicate)

    def emit(self, method, path, body, response):
        request = FakeRequest(method, path, body, self.context.token or "")
        result = FakeResponse(request, response)
        if path in self.response_request_changes:
            result.request = FakeRequest(method, path, {**body, **self.response_request_changes[path]}, self.context.token or "")
        self.requests.append(request)
        for listener in self.listeners:
            listener(request)
        for kind, value in (("request", request), ("response", result)):
            for item in self.active[kind]:
                if not item.value.done() and item.predicate(value):
                    item.value.set_result(value)

    def get_by_role(self, role, *, name, **kwargs):
        return FakeLocator(self, "confirm" if isinstance(name, re.Pattern) else name)

    def get_by_label(self, name, **kwargs):
        return FakeLocator(self, name)

    def get_by_text(self, name, **kwargs):
        return FakeLocator(self, name)

    def locator(self, value):
        return FakeLocator(self, value)

    async def evaluate(self, script, data):
        assert "BigInt" in script and "timeZone:'UTC'" in script
        assert data["facts"] == FACTS
        return {"amount": "42,00" if data["language"] == "pt" else "42.00",
                "date": "20 de setembro de 2026" if data["language"] == "pt" else "20 de septiembre de 2026"}

    def evidence_text(self):
        amount = "42,00" if self.language == "pt" else "42.00"
        date = "20 de setembro de 2026" if self.language == "pt" else "20 de septiembre de 2026"
        return " ".join((REFERENCE, "fixture-1", FACTS["merchant"], "COP", amount, date, RECEIPT["id"]))

    async def reload(self):
        self.emit("GET", "/api/auth/me", None, IDENTITY)
        self.emit("GET", "/api/overview", None, self.overview)


class FakeTruth:
    def __init__(self, scope):
        self.scope, self.admission_changes, self.pending_changes, self.receipt_changes = scope, {}, {}, {}
        self.pending_calls = 0
        self.build = BUILD_SHA

    async def static_build_sha256(self, page, source_revision):
        assert source_revision == REVISION
        return self.build

    async def owned_selection(self, selected, overview, cookie):
        values = dict(selection_sha256=digest({"selection": selected, "metadata": overview["metadata"],
            "profile": overview["profile"]}), fixture_id=FIXTURE.fixture_id,
            frontend_source_revision=REVISION, static_build_sha256=BUILD_SHA, cookie_sha256=cookie,
            ledger_generation=ATTESTED.ledger_generation, backend_truth_sha256="1" * 64,
            generated_only=True, owner_verified=True)
        return OwnedSelectionTruth(**{**values, **self.admission_changes})

    async def pending(self, saved, cookie):
        self.pending_calls += 1
        return PendingTruth(**{**dict(tuple_sha256=digest(saved.public()), cookie_sha256=cookie,
            ledger_generation=ATTESTED.ledger_generation, backend_truth_sha256="2" * 64, receipt_absent=True),
            **self.pending_changes})

    async def fresh_receipt(self, saved, cookie):
        return ReceiptTruth(**{**dict(tuple_sha256=digest(saved.public()), cookie_sha256=cookie,
            ledger_generation=ATTESTED.ledger_generation, backend_truth_sha256="3" * 64,
            receipt_sha256=digest(RECEIPT), receipt=deepcopy(RECEIPT), fresh=True), **self.receipt_changes})


class SyntheticFrontendBrowserTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def probe(self, root=None):
        scope = BrowserScope(FIXTURE, ATTESTED, ORIGIN, REVISION, BUILD_SHA,
                             Path(root or self.directory.name), "LC Lucía Colombia · COP", "pure-fake-page")
        context = FakeContext()
        page = FakePage(context)
        truth = FakeTruth(scope)
        return FrontendBrowserProbe(page, context, scope, truth), page, context, truth

    async def prepared(self, language="es", root=None):
        probe, page, context, truth = self.probe(root)
        await probe.login_and_select(CODE, lambda rows: rows[0]["reference"])
        await probe.inquire("No reconozco este cargo sintético")
        await probe.set_language(language)
        await probe.prepare()
        return probe, page, context, truth

    async def test_full_fake_shipped_selectors_es_pt_consent_body_receipt_and_artifact_redaction(self):
        for language in COPY:
            with self.subTest(language=language):
                # Isolate screenshot roots across languages and repeated fake journeys.
                with tempfile.TemporaryDirectory() as path:
                        probe, page, _, truth = await self.prepared(language, path)
                        self.assertEqual(probe.saved.request_id, SERVER_UUID)
                        self.assertEqual(probe.browser_prepare_request_id, BROWSER_UUID)
                        await probe.click_confirm()
                        self.assertEqual(truth.pending_calls, 2)
                        confirm = [r for r in page.requests if r.url.endswith("/api/action/confirm")]
                        self.assertEqual(len(confirm), 1)
                        self.assertEqual(confirm[0].post_data_json, {"pending_handle": HANDLE,
                            "transaction_reference": REFERENCE, "confirmed": True, "language": language})
                        self.assertIn((COPY[language]["disclosure"], "visible"), page.waits)
                        self.assertTrue(any("consent-panel" in x for x in page.screenshot_paths))
                        self.assertEqual(probe.receipt, RECEIPT)
                        report = probe.report()
                        self.assertFalse(report["human_acceptance"])
                        self.assertFalse(report["learned_model_acceptance"])
                        self.assertEqual(report["runtime_kind"], "pure-fake-page")
                        for artifact in report["screenshots"]:
                            self.assertEqual(artifact["sha256"], hashlib.sha256(Path(artifact["path"]).read_bytes()).hexdigest())
                        serialized = json.dumps(report, ensure_ascii=False)
                        for secret in (TOKEN, HANDLE, CODE, "cookie", "headers", "post_data"):
                            self.assertNotIn(secret, serialized)
                        with self.assertRaises(DriverError):
                            await probe.click_confirm()

    async def test_uncertain_click_reload_retry_preserves_tuple_without_second_post_or_overwrite(self):
        probe, page, _, _ = await self.prepared("pt")
        page.confirm_response = pending(state="action_unverified")
        await probe.click_confirm()
        saved = probe.saved.public()
        page.state = terminal()
        await probe.recover_after_external_restart()
        await probe.retry_status()
        self.assertEqual(probe.saved.public(), saved)
        self.assertEqual(probe.writes, {"/api/action/prepare": 1, "/api/action/confirm": 1})
        self.assertEqual(len(set(page.screenshot_paths)), len(page.screenshot_paths))
        self.assertTrue(all(Path(path).is_file() for path in page.screenshot_paths))
        with self.assertRaises(DriverError):
            await probe.click_confirm()

    async def test_response_request_must_match_observed_browser_prepare_body(self):
        probe, page, _, truth = self.probe()
        await probe.login_and_select(CODE, lambda rows: rows[0]["reference"])
        await probe.inquire("Consulta sintética")
        page.response_request_changes["/api/action/prepare"] = {"request_id": SERVER_UUID}
        with self.assertRaises(DriverError):
            await probe.prepare()
        self.assertEqual(truth.pending_calls, 0)
        self.assertIsNone(probe.saved)

    async def test_changed_restart_charge_stops_before_any_new_screenshot_or_post(self):
        probe, page, _, _ = await self.prepared()
        page.confirm_response = pending(state="action_unverified")
        await probe.click_confirm()
        page.overview["transactions"][0]["amount"] = 43.0
        count = len(page.screenshot_paths)
        with self.assertRaises(DriverError):
            await probe.recover_after_external_restart()
        self.assertEqual(len(page.screenshot_paths), count)
        self.assertEqual(probe.writes["/api/action/confirm"], 1)

    async def test_foreign_reference_or_untrusted_fixture_is_rejected_before_screenshot(self):
        for changes in ({"generated_only": False}, {"owner_verified": False},
                        {"selection_sha256": "0" * 64}, {"ledger_generation": "0" * 64},
                        {"fixture_id": "organizer"}, {"frontend_source_revision": "0" * 40}):
            with self.subTest(changes=changes):
                probe, page, _, truth = self.probe()
                truth.admission_changes = changes
                with self.assertRaises(DriverError):
                    await probe.login_and_select(CODE, lambda rows: rows[0]["reference"])
                self.assertEqual(page.screenshot_paths, [])
        probe, page, _, _ = self.probe()
        with self.assertRaises(DriverError):
            await probe.login_and_select(CODE, lambda rows: "txn_" + "c" * 24)
        self.assertEqual(page.screenshot_paths, [])

    async def test_current_cookie_pending_absence_build_and_summary_guard_before_confirmation(self):
        for kind in ("cookie", "absence", "generation", "build", "summary"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as path:
                    probe, page, context, truth = await self.prepared(root=path)
                    if kind == "cookie": context.token = "changed"
                    elif kind == "absence": truth.pending_changes = {"receipt_absent": False}
                    elif kind == "generation": truth.pending_changes = {"ledger_generation": "0" * 64}
                    elif kind == "build": truth.build = "0" * 64
                    else: page.summary = "This charge"
                    with self.assertRaises(DriverError):
                        await probe.click_confirm()
                    self.assertEqual(probe.writes["/api/action/confirm"], 0)

    async def test_confirm_wire_or_receipt_drift_is_rejected(self):
        for kind in ("body", "handle", "target", "uuid", "facts", "truth", "fresh"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as path:
                    probe, page, _, truth = await self.prepared(root=path)
                    if kind == "body": page.confirm_body_changes = {"confirmed": False}
                    elif kind == "handle": page.confirm_response = terminal(pending_handle="q" * 43)
                    elif kind == "target": page.confirm_response = terminal(target_reference="txn_" + "c" * 24)
                    elif kind == "uuid": page.confirm_response = terminal(request_id=BROWSER_UUID)
                    elif kind == "facts": page.confirm_response = terminal(receipt={**RECEIPT, "transaction": {**FACTS, "amount": "43.00"}})
                    elif kind == "truth": truth.receipt_changes = {"receipt_sha256": "0" * 64}
                    else: truth.receipt_changes = {"fresh": False}
                    with self.assertRaises(DriverError):
                        await probe.click_confirm()
                    self.assertIsNone(probe.receipt)
                    self.assertFalse(any("verified-receipt" in x for x in page.screenshot_paths))

    async def test_unsolicited_intake_and_login_forms_cannot_become_evidence(self):
        probe, page, _, _ = await self.prepared()
        with self.assertRaises(DriverError):
            probe._same_tuple(terminal(request_id=SERVER_UUID))
        page.login_visible = True
        before = len(page.screenshot_paths)
        with self.assertRaises(DriverError):
            await probe._screen(page.locator(".action-panel"), "consent-panel")
        self.assertEqual(len(page.screenshot_paths), before)

    async def test_existing_artifact_and_changed_selection_cannot_be_captured(self):
        probe, page, _, _ = await self.prepared()
        existing = Path(self.directory.name) / f"browser-{REVISION[:12]}-002-es-consent-panel.png"
        existing.write_bytes(b"existing proof")
        with self.assertRaises(DriverError):
            await probe._screen(page.locator(".action-panel"), "consent-panel")
        self.assertEqual(existing.read_bytes(), b"existing proof")
        probe.selection["merchant"] = "Foreign Merchant"
        with self.assertRaises(DriverError):
            await probe._screen(page.locator(".action-panel"), "another")

    async def test_fresh_cookie_and_effective_source_pin_are_required(self):
        for kind in ("cookie", "build"):
            with self.subTest(kind=kind):
                probe, page, context, truth = self.probe()
                if kind == "cookie": context.token = TOKEN
                else: truth.build = "0" * 64
                with self.assertRaises(DriverError):
                    await probe.login_and_select(CODE, lambda rows: rows[0]["reference"])
                self.assertEqual(page.screenshot_paths, [])
