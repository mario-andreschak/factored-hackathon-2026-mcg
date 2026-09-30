"""Separately scoped test-only probe of an injected, already-open Playwright page.

No browser launch, URL default, API client, routing override, trace/HAR capture,
CLI or backend write is provided. Trusted callbacks verify the effective static
build and actual owner-bound pending/receipt rows. Automation is not human or
learned-model acceptance. Hosted execution needs its own exact-source review.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
from http.cookies import SimpleCookie
import json
from pathlib import Path
import re
from typing import Any, Protocol
from urllib.parse import urlsplit

from frontend.server.action import matches_selected_transaction, project_action_result, verified_receipt
from scripts.synthetic_integration.frontend_driver import AttestedPhaseEvidence, DriverError, GeneratedFixture


# Copied from shipped App.tsx: login 309/346, charge 648/861/891,
# assistant 2081/2120/2493/2505, action 945/958/959/2264/2297, receipt 1462.
COPY = {
    "es": {"language": "Idioma de esta respuesta", "prepare": "Revisar recepción simulada",
           "confirm": "Confirmo la recepción simulada para", "reveal": "Mostrar monto para confirmar",
           "status": "Consultar estado de la solicitud", "receipt": "Comprobante local",
           "disclosure": "La recepción es una simulación. No bloquea tarjetas, devuelve dinero ni resuelve una disputa."},
    "pt": {"language": "Idioma desta resposta", "prepare": "Revisar registro simulado",
           "confirm": "Confirmo o registro simulado para", "reveal": "Mostrar valor para confirmar",
           "status": "Consultar estado da solicitação", "receipt": "Comprovante local",
           "disclosure": "O registro é uma simulação. Não bloqueia cartões, devolve dinheiro nem resolve uma contestação."},
}
_HASH = re.compile(r"^[a-f0-9]{64}$")
_UUID = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")
_ROUTES = {"/api/auth/login", "/api/auth/me", "/api/overview", "/api/chat/messages",
           "/api/action/prepare", "/api/action/confirm", "/api/action/status"}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class BrowserScope:
    fixture: GeneratedFixture
    attested_phase: AttestedPhaseEvidence
    frontend_origin: str
    frontend_source_revision: str
    static_build_sha256: str
    fixture_root: Path
    profile_button_name: str
    runtime_kind: str  # Explicitly "pure-fake-page" or "hosted-playwright".

    def __post_init__(self):
        if not isinstance(self.fixture, GeneratedFixture) or not isinstance(self.attested_phase, AttestedPhaseEvidence):
            raise DriverError("Typed independent generated-only setup required")
        origin = urlsplit(self.frontend_origin)
        if (origin.scheme not in {"http", "https"} or not origin.hostname or origin.path
                or origin.username or origin.password or origin.query or origin.fragment
                or (origin.scheme == "http" and origin.hostname not in {"localhost", "127.0.0.1", "::1"})
                or not re.fullmatch(r"[a-f0-9]{40}", self.frontend_source_revision)
                or not _HASH.fullmatch(self.static_build_sha256)
                or not isinstance(self.fixture_root, Path) or not self.fixture_root.is_absolute()
                or not self.profile_button_name or self.runtime_kind not in {"pure-fake-page", "hosted-playwright"}
                or self.attested_phase.fixture_id != self.fixture.fixture_id
                or self.attested_phase.build_id != self.fixture.build_id
                or self.attested_phase.source_fingerprint != self.fixture.source_fingerprint):
            raise DriverError("Explicit source-pinned generated-only browser scope required")


@dataclass(frozen=True)
class SavedTuple:
    request_id: str
    target_reference: str
    pending_handle: str  # Capability retained in memory, never emitted in a report.
    snapshot: str
    facts: dict

    def public(self) -> dict:
        return {"request_id": self.request_id, "target_reference": self.target_reference,
                "pending_handle_sha256": hashlib.sha256(self.pending_handle.encode()).hexdigest(),
                "snapshot": self.snapshot, "facts": deepcopy(self.facts)}


@dataclass(frozen=True)
class OwnedSelectionTruth:
    selection_sha256: str  # Exact public row + overview profile/metadata digest.
    fixture_id: str
    frontend_source_revision: str
    static_build_sha256: str
    cookie_sha256: str
    ledger_generation: str
    backend_truth_sha256: str
    generated_only: bool
    owner_verified: bool


@dataclass(frozen=True)
class PendingTruth:
    tuple_sha256: str
    cookie_sha256: str
    ledger_generation: str
    backend_truth_sha256: str
    receipt_absent: bool


@dataclass(frozen=True)
class ReceiptTruth:
    tuple_sha256: str
    cookie_sha256: str
    ledger_generation: str
    backend_truth_sha256: str
    receipt_sha256: str
    receipt: dict
    fresh: bool


class TruthVerifier(Protocol):
    async def static_build_sha256(self, page: Any, source_revision: str) -> str: ...

    async def owned_selection(self, selection: dict, overview: dict, cookie_sha256: str) -> OwnedSelectionTruth: ...

    async def pending(self, saved: SavedTuple, cookie_sha256: str) -> PendingTruth: ...

    async def fresh_receipt(self, saved: SavedTuple, cookie_sha256: str) -> ReceiptTruth: ...


class FrontendBrowserProbe:
    def __init__(self, page: Any, context: Any, scope: BrowserScope, verifier: TruthVerifier):
        self.page, self.context, self.scope, self.verifier = page, context, scope, verifier
        self.selection: dict | None = None
        self.saved: SavedTuple | None = None
        self.language = "es"
        self.cookie_sha256: str | None = None
        self.inquiry_completed = False
        self.browser_prepare_request_id: str | None = None
        self.confirmation_attempted = False
        self.confirmation_clicked = False
        self.receipt: dict | None = None
        self.owned_overview: dict | None = None
        self.admitted_selection_sha256: str | None = None
        self.steps: list[dict] = []
        self.screenshots: list[dict] = []
        self.truth_digests: list[str] = []
        self.writes = {"/api/action/prepare": 0, "/api/action/confirm": 0}
        self.page.on("request", self._observe_request)

    def _matches(self, value: Any, method: str, path: str) -> bool:
        parsed = urlsplit(value.url)
        request = value if hasattr(value, "method") else value.request
        return (parsed.scheme + "://" + parsed.netloc == self.scope.frontend_origin
                and parsed.path == path and request.method == method)

    def _observe_request(self, request: Any) -> None:
        path = urlsplit(request.url).path
        if path in _ROUTES and self._matches(request, request.method, path):
            self.steps.append({"step": "request_observed", "method": request.method, "path": path})
            if request.method == "POST" and path in self.writes:
                self.writes[path] += 1
                if path == "/api/action/confirm" and self.confirmation_attempted:
                    self.confirmation_clicked = True

    def _no_duplicate_writes(self) -> None:
        if any(count > 1 for count in self.writes.values()):
            raise DriverError("Browser emitted duplicate prepare or confirmation writes")

    async def _cookie(self, *, fresh: bool = False) -> str | None:
        # Inspect only the current origin; never dump cookies or storage.
        cookies = [item for item in await self.context.cookies([self.scope.frontend_origin])
                   if item.get("name") == "flujo_bank_session"]
        if fresh:
            if cookies:
                raise DriverError("Fresh browser context already has a banking cookie")
            return None
        if len(cookies) != 1 or not isinstance(cookies[0].get("value"), str) or not cookies[0]["value"]:
            raise DriverError("Current browser banking session is missing")
        result = hashlib.sha256(cookies[0]["value"].encode()).hexdigest()
        if self.cookie_sha256 is not None and result != self.cookie_sha256:
            raise DriverError("Browser session changed")
        return result

    async def _request_cookie(self, request: Any) -> None:
        headers = await request.all_headers()
        cookies = SimpleCookie()
        cookies.load(headers.get("cookie", ""))
        token = cookies.get("flujo_bank_session")
        if token is None or hashlib.sha256(token.value.encode()).hexdigest() != self.cookie_sha256:
            raise DriverError("Observed request did not use the current browser cookie")

    async def _click(self, locator: Any, method: str, path: str, expected: dict | None = None,
                     *, login: bool = False, request_check=None) -> dict:
        # Both observers are attached before the shipped control is clicked.
        async with self.page.expect_request(lambda value: self._matches(value, method, path)) as request_info:
            async with self.page.expect_response(lambda value: self._matches(value, method, path)) as response_info:
                await locator.click()
        request, response = await request_info.value, await response_info.value
        if (expected is not None and request.post_data_json != expected
                or method == "POST" and response.request.post_data_json != request.post_data_json
                or request_check is not None and not request_check(request.post_data_json)):
            raise DriverError("Shipped control emitted a different request body")
        if not login:
            await self._request_cookie(request)
            await self._request_cookie(response.request)
        if response.status != 200:
            raise DriverError("Observed frontend response did not succeed")
        result = await response.json()
        if not isinstance(result, dict):
            raise DriverError("Observed frontend response is not an object")
        self._no_duplicate_writes()
        return result

    async def _build(self) -> None:
        parsed = urlsplit(self.page.url)
        if parsed.scheme + "://" + parsed.netloc != self.scope.frontend_origin:
            raise DriverError("Existing browser page has a different origin")
        if await self.verifier.static_build_sha256(self.page, self.scope.frontend_source_revision) != self.scope.static_build_sha256:
            raise DriverError("Effective static frontend build changed")

    def _overview(self, body: dict) -> list[dict]:
        meta, profile = body.get("metadata", {}), body.get("profile", {})
        if (not isinstance(meta, dict) or not isinstance(profile, dict)
                or profile.get("id") != self.scope.fixture.profile or meta.get("build_id") != self.scope.fixture.build_id
                or meta.get("source_fingerprint") != self.scope.fixture.source_fingerprint
                or not isinstance(body.get("transactions"), list)
                or any(not isinstance(row, dict) for row in body["transactions"])):
            raise DriverError("Browser overview is not the declared owned fixture")
        return body["transactions"]

    def _dialog(self, heading: str):
        return self.page.locator("dialog").filter(has=self.page.get_by_role("heading", name=heading, exact=True))

    async def _screen(self, locator: Any, step: str) -> None:
        if (self.admitted_selection_sha256 is None or self.owned_overview is None
                or self.admitted_selection_sha256 != self._selection_digest(self.owned_overview)):
            raise DriverError("Screenshot requires exact generated-only owned selection admission")
        await self._cookie()
        if await self.page.locator("#login-code").count():
            raise DriverError("Login forms and access codes cannot appear in screenshots")
        root = self.scope.fixture_root.resolve(strict=True)
        if not root.is_dir():
            raise DriverError("Explicit existing fixture artifact directory required")
        ordinal = len(self.screenshots) + 1
        path = (root / f"browser-{self.scope.frontend_source_revision[:12]}-{ordinal:03d}-{self.language}-{step}.png").resolve()
        if path.parent != root or path.exists():
            raise DriverError("Screenshot path escaped fixture root or would overwrite an artifact")
        returned = await locator.screenshot(path=str(path))
        written = path.read_bytes()
        if not written.startswith(b"\x89PNG\r\n\x1a\n") or returned != written:
            raise DriverError("Written fictional screenshot differs from returned PNG bytes")
        self.screenshots.append({"step": ordinal, "path": str(path), "sha256": hashlib.sha256(written).hexdigest()})

    def _selection_digest(self, overview: dict) -> str:
        return digest({"selection": self.selection, "metadata": overview["metadata"], "profile": overview["profile"]})

    async def _admit_selection(self, overview: dict) -> None:
        self.admitted_selection_sha256 = None
        proof = await self.verifier.owned_selection(deepcopy(self.selection), deepcopy(overview), self.cookie_sha256)
        if (not isinstance(proof, OwnedSelectionTruth) or proof.generated_only is not True or proof.owner_verified is not True
                or proof.selection_sha256 != self._selection_digest(overview)
                or proof.fixture_id != self.scope.fixture.fixture_id
                or proof.frontend_source_revision != self.scope.frontend_source_revision
                or proof.static_build_sha256 != self.scope.static_build_sha256
                or proof.cookie_sha256 != self.cookie_sha256
                or proof.ledger_generation != self.scope.attested_phase.ledger_generation
                or not _HASH.fullmatch(proof.backend_truth_sha256)):
            raise DriverError("Selection has no exact generated-only owner admission")
        self.owned_overview = deepcopy(overview)
        self.admitted_selection_sha256 = proof.selection_sha256
        self.truth_digests.append(proof.backend_truth_sha256)

    async def login_and_select(self, code: str, selector) -> dict:
        await self._build()
        await self._cookie(fresh=True)
        await self.page.get_by_role("button", name=self.scope.profile_button_name, exact=True).click()
        await self.page.get_by_label("Código de acceso", exact=True).fill(code)
        async with self.page.expect_response(lambda value: self._matches(value, "GET", "/api/overview")) as overview_info:
            login = await self._click(self.page.get_by_role("button", name="Entrar a mi banca", exact=True),
                "POST", "/api/auth/login", {"profile": self.scope.fixture.profile, "code": code}, login=True)
        if login.get("authenticated") is not True or login.get("auth_mode") != "demo" or login.get("profile", {}).get("id") != self.scope.fixture.profile:
            raise DriverError("Shipped login did not bind the declared demo profile")
        self.cookie_sha256 = await self._cookie()
        overview_response = await overview_info.value
        if overview_response.status != 200:
            raise DriverError("Owned overview did not load")
        await self._request_cookie(overview_response.request)
        overview = await overview_response.json()
        rows = self._overview(overview)
        reference = selector(deepcopy(rows))
        selected = [row for row in rows if row.get("reference") == reference]
        if len(selected) != 1 or not isinstance(reference, str) or not re.fullmatch(r"txn_[a-f0-9]{24}", reference):
            raise DriverError("Browser selection is not a unique owned overview reference")
        self.selection = deepcopy(selected[0])
        await self._admit_selection(overview)
        await self._open_charge()
        return deepcopy(self.selection)

    async def _open_charge(self) -> None:
        if self.selection is None or not self.selection.get("merchant"):
            raise DriverError("A named generated charge is required")
        row = self.page.locator(".transaction-row").filter(has_text=self.selection["merchant"])
        await row.wait_for(state="visible")
        if await row.count() != 1:
            raise DriverError("Displayed generated charge is ambiguous")
        await row.click()
        dialog = self._dialog("Detalle del movimiento")
        await dialog.wait_for(state="visible")
        text = await dialog.inner_text()
        if self.selection["reference"] not in text or self.selection["merchant"] not in text or self.selection["currency"] not in text:
            raise DriverError("Charge dialog does not identify the owned selection")
        await self._screen(dialog, "owned-charge")

    async def inquire(self, message: str) -> dict:
        if self.selection is None or not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
            raise DriverError("A bounded selected-charge inquiry is required")
        await self.page.get_by_role("button", name="Revisar este cargo", exact=True).click()
        await self.page.get_by_role("textbox", name="Mensaje para el asistente", exact=True).fill(message.strip())
        result = await self._click(self.page.get_by_role("button", name="Enviar mensaje", exact=True),
            "POST", "/api/chat/messages", {"message": message.strip(), "transaction_reference": self.selection["reference"]})
        if result.get("status") != "completed" or result.get("mode") != "flujo":
            raise DriverError("Disclosed deterministic fixture inquiry did not complete")
        self.inquiry_completed = True
        self.steps.append({"step": "selected_inquiry", "outcome": "deterministic-provider-fixture-completion"})
        return result

    async def set_language(self, language: str) -> None:
        if language not in COPY:
            raise DriverError("ES/PT action language required")
        control = self._dialog("Tu asistente Savia").get_by_role("combobox", name=COPY[self.language]["language"], exact=True)
        if language != self.language:
            async with self.page.expect_response(lambda value: self._matches(value, "GET", "/api/action/status")):
                await control.select_option(language)
            self.language = language
        await self.page.get_by_text(COPY[language]["disclosure"], exact=True).wait_for(state="visible")
        self.steps.append({"step": "action_disclosure", "language": language, "outcome": "visible"})

    def _same_tuple(self, body: dict) -> dict:
        projected = project_action_result(body)
        if self.saved is None or projected["state"] != body.get("state"):
            raise DriverError("Missing or malformed browser action evidence")
        if projected["state"] == "intake_verified" and not self.confirmation_clicked:
            raise DriverError("A new receipt cannot precede the observed shipped confirmation")
        wire_uuid = projected.get("request_id")
        if (wire_uuid != self.saved.request_id and not (wire_uuid is None and self.confirmation_clicked
                and projected["state"] in {"action_unverified", "intake_verified"})):
            raise DriverError("Saved browser prepare UUID changed")
        evidence = projected["receipt"] if projected["state"] == "intake_verified" else projected
        if (projected.get("target_reference") != self.saved.target_reference
                or projected.get("pending_handle") != self.saved.pending_handle
                or evidence.get("snapshot") != self.saved.snapshot
                or evidence.get("transaction") != self.saved.facts
                or "transaction" in projected and (projected["transaction"] != self.saved.facts
                                                    or projected["snapshot"] != self.saved.snapshot)):
            raise DriverError("Saved browser handle, target or facts changed")
        return projected

    def _truth(self, proof: Any) -> None:
        if (self.saved is None or proof.tuple_sha256 != digest(self.saved.public())
                or proof.cookie_sha256 != self.cookie_sha256
                or proof.ledger_generation != self.scope.attested_phase.ledger_generation
                or not _HASH.fullmatch(proof.backend_truth_sha256)):
            raise DriverError("Independent backend truth does not bind this browser tuple")
        self.truth_digests.append(proof.backend_truth_sha256)

    async def prepare(self) -> SavedTuple:
        if (not self.inquiry_completed or self.selection is None or self.saved is not None
                or self.writes["/api/action/prepare"] != 0):
            raise DriverError("Only one fresh browser prepare intent is supported")
        def exact_browser_intent(body):
            if (not isinstance(body, dict) or set(body) != {"transaction_reference", "request_id", "language"}
                    or body["transaction_reference"] != self.selection["reference"]
                    or body["language"] != self.language or not isinstance(body["request_id"], str)
                    or not _UUID.fullmatch(body["request_id"])):
                return False
            # Shipped crypto.randomUUID is observed independently of server authority.
            self.browser_prepare_request_id = body["request_id"]
            return True
        body = await self._click(self.page.get_by_role("button", name=COPY[self.language]["prepare"], exact=True),
            "POST", "/api/action/prepare", request_check=exact_browser_intent)
        if self.writes["/api/action/prepare"] != 1:
            raise DriverError("Exactly one shipped browser prepare POST must be observed")
        result = project_action_result(body)
        if (result["state"] != "pending_confirmation" or result.get("snapshot") != self.scope.fixture.build_id
                or result.get("target_reference") != self.selection["reference"]
                or not isinstance(result.get("request_id"), str) or not _UUID.fullmatch(result["request_id"])
                or not matches_selected_transaction(result.get("transaction"), self.selection)):
            raise DriverError("Positive browser phase has no exact verified pending charge")
        self.saved = SavedTuple(result["request_id"], result["target_reference"], result["pending_handle"], result["snapshot"], result["transaction"])
        await self._pending_truth()
        return self.saved

    async def _pending_truth(self) -> None:
        await self._cookie()
        proof = await self.verifier.pending(self.saved, self.cookie_sha256)
        if not isinstance(proof, PendingTruth) or proof.receipt_absent is not True:
            raise DriverError("Independent backend verifier did not prove fresh pending receipt absence")
        self._truth(proof)

    async def _formatted_facts(self) -> dict:
        # Same Intl formatting as shipped actionDate/evidenceAmount, no clock mutation.
        return await self.page.evaluate("""({facts, language}) => {
          const locale = language === 'pt' ? 'pt-BR' : 'es-MX';
          const [whole, fraction = ''] = facts.amount.split('.');
          const decimal = new Intl.NumberFormat(locale).formatToParts(1.1).find(p => p.type === 'decimal').value;
          return {amount: new Intl.NumberFormat(locale).format(BigInt(whole)) + decimal + fraction.padEnd(2,'0'),
            date: new Intl.DateTimeFormat(locale,{day:'2-digit',month:'long',year:'numeric',timeZone:'UTC'})
              .format(new Date(facts.transaction_date.slice(0,10)+'T12:00:00Z'))};
        }""", {"facts": self.saved.facts, "language": self.language})

    async def _display_receipt(self, result: dict) -> None:
        receipt = verified_receipt(result.get("receipt"))
        proof = await self.verifier.fresh_receipt(self.saved, self.cookie_sha256)
        if (receipt is None or not isinstance(proof, ReceiptTruth) or proof.fresh is not True
                or verified_receipt(proof.receipt) != receipt or proof.receipt_sha256 != digest(receipt)
                or receipt["snapshot"] != self.saved.snapshot or receipt["transaction"] != self.saved.facts
                or self.receipt is not None and receipt != self.receipt):
            raise DriverError("Displayed receipt conflicts with fresh backend truth")
        self._truth(proof)
        region = self.page.get_by_role("region", name=COPY[self.language]["receipt"], exact=True)
        await region.wait_for(state="visible")
        text = await region.inner_text()
        formatted = await self._formatted_facts()
        for value in (receipt["id"], self.saved.target_reference, receipt["snapshot"], receipt["transaction"]["merchant"],
                      receipt["transaction"]["currency"], formatted["amount"], formatted["date"]):
            if value and value not in text:
                raise DriverError("Fresh receipt is not visibly tied to its owned facts")
        self.receipt = receipt
        await self._screen(region, "verified-receipt")
        self.steps.append({"step": "fresh_receipt_display", "language": self.language, "outcome": "verified", "receipt_id": receipt["id"]})

    async def click_confirm(self) -> dict:
        if (self.saved is None or self.confirmation_attempted
                or self.writes["/api/action/confirm"] != 0):
            raise DriverError("No fresh independently verified browser consent is available")
        button = self.page.get_by_role("button", name=re.compile("^" + re.escape(COPY[self.language]["confirm"])))
        await button.wait_for(state="visible")
        if not await button.is_enabled():
            await self.page.get_by_role("button", name=COPY[self.language]["reveal"], exact=True).click()
        summary_id = await button.get_attribute("aria-describedby")
        if not summary_id or not re.fullmatch(r"[A-Za-z0-9:_-]+", summary_id):
            raise DriverError("Shipped confirmation lacks its accessible saved-charge summary")
        summary = await self.page.locator('[id="' + summary_id + '"]').inner_text()
        formatted = await self._formatted_facts()
        for value in (self.saved.target_reference, self.saved.snapshot, self.saved.facts["merchant"],
                      self.saved.facts["currency"], formatted["amount"], formatted["date"]):
            if value and value not in summary:
                raise DriverError("Consent summary does not name the exact saved charge")
        await self._build()
        await self._pending_truth()  # Current cookie/generation and receipt absence just before click.
        await self._screen(self._dialog("Tu asistente Savia").locator(".action-panel"), "consent-panel")
        self.confirmation_attempted = True
        result = self._same_tuple(await self._click(button, "POST", "/api/action/confirm", {
            "pending_handle": self.saved.pending_handle, "transaction_reference": self.saved.target_reference,
            "confirmed": True, "language": self.language}))
        if result["state"] == "intake_verified":
            await self._display_receipt(result)
        elif result["state"] != "action_unverified":
            raise DriverError("Confirmation did not return verified receipt or explicit uncertainty")
        return result

    async def retry_status(self) -> dict:
        if not self.confirmation_clicked:
            raise DriverError("Recovery must follow the one observed confirmation click")
        result = self._same_tuple(await self._click(self.page.get_by_role("button", name=COPY[self.language]["status"], exact=True), "GET", "/api/action/status"))
        if result["state"] == "intake_verified":
            await self._display_receipt(result)
        elif result["state"] != "action_unverified":
            raise DriverError("Receipt recovery has an unexpected outcome")
        await self.page.get_by_role("button", name=re.compile(r"^Confirmo")).wait_for(state="hidden")
        self._no_duplicate_writes()
        return result

    async def recover_after_external_restart(self) -> dict:
        if not self.confirmation_clicked:
            raise DriverError("No uncertain or completed confirmation exists to recover")
        async with self.page.expect_response(lambda value: self._matches(value, "GET", "/api/auth/me")) as identity_info:
            async with self.page.expect_response(lambda value: self._matches(value, "GET", "/api/overview")) as overview_info:
                await self.page.reload()
        identity_response, overview_response = await identity_info.value, await overview_info.value
        if identity_response.status != 200 or overview_response.status != 200:
            raise DriverError("Restart did not restore authenticated overview")
        await self._request_cookie(identity_response.request)
        await self._request_cookie(overview_response.request)
        identity = await identity_response.json()
        if identity.get("authenticated") is not True or identity.get("auth_mode") != "demo" or identity.get("profile", {}).get("id") != self.scope.fixture.profile:
            raise DriverError("Restart changed the owned browser profile")
        overview = await overview_response.json()
        if self.selection not in self._overview(overview):
            raise DriverError("Restart changed the owned browser charge")
        await self._build()
        await self._cookie()
        await self._admit_selection(overview)
        await self._open_charge()
        result = self._same_tuple(await self._click(self.page.get_by_role("button", name="Revisar este cargo", exact=True), "GET", "/api/action/status"))
        if result["state"] == "intake_verified":
            await self._display_receipt(result)
        elif result["state"] != "action_unverified":
            raise DriverError("Restart receipt recovery has an unexpected outcome")
        await self.page.get_by_role("button", name=re.compile(r"^Confirmo")).wait_for(state="hidden")
        self._no_duplicate_writes()
        return result

    def report(self) -> dict:
        return deepcopy({"scope": "separate-generated-fixture-browser-automation", "runtime_kind": self.scope.runtime_kind,
            "frontend_source_revision": self.scope.frontend_source_revision,
            "static_build_sha256": self.scope.static_build_sha256, "fixture_id": self.scope.fixture.fixture_id,
            "build_id": self.scope.fixture.build_id, "source_fingerprint": self.scope.fixture.source_fingerprint,
            "language": self.language, "automation_confirmation_click_observed": self.confirmation_clicked,
            "human_acceptance": False, "learned_model_acceptance": False,
            "hosted_execution_review": "separate exact-source review required",
            "steps": self.steps, "screenshots": self.screenshots, "backend_truth_sha256": self.truth_digests,
            "observed_frontend_writes": self.writes,
            "limitations": ["Deterministic provider fixture completion is not model grounding.",
                "Generated-only origin and attestation are independently verified setup inputs.",
                "Automation click is not actual human acceptance.",
                "Typed backend truth and effective static-build adapters remain independently reviewed assembly dependencies.",
                "Frontend status GET may invoke exact idempotent recovery upstream; independent backend counts remain required."]})

    def close(self) -> None:
        self.page.remove_listener("request", self._observe_request)
