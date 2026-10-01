"""Qualify the isolated Dispute app over HTTP using newly generated fiction.

The native worker and its private authority directory must already be installed.
This program never installs a worker, changes a model binding, or reads a real
bank dataset. All source, signer and sandbox state stay in a fresh private
directory. The separately selected output contains hashes and bounded outcomes.

Run ``--prepare-only`` to publish the fixture without contacting any provider.
``build_fixture`` and ``run_qualification(..., port_factory=...)`` are injectable
for offline tests; a controlled port is explicitly reported as non-native.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import threading
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SCHEMA = "dispute-joined-native-http-qualification/v1"
_SAFE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_OBSERVATION_FIELDS = {
    "stage", "model", "status", "prompt_tokens", "completion_tokens",
    "total_tokens", "cached_prompt_tokens", "cache_write_tokens",
    "reasoning_tokens", "cost_usd", "request_system_chars", "request_user_chars",
    "latency_ms", "response_model", "response_id_kind",
}
_STAGES = {"preflight_batch", "detect_attack", "detect_context", "rewrite_decompose", "detect_intent",
           "extract_slots", "resolve_clarification", "generate", "generate_handoff_summary"}
_NODES = _STAGES | {"get_customer_profile", "search_transactions", "get_transaction", "get_related_complaints",
    "get_complaint", "list_customer_complaints", "host_action_status", "retrieve_policy", "query_preflight_barrier",
    "parallel_preflight", "motor_policy", "compose_responses"}


def _utc(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("timezone-aware fixture time required")
    return now.astimezone(timezone.utc)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _private_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _tree_hashes(root: Path, *, suffixes: tuple[str, ...] | None = None) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): _digest(path.read_bytes())
            for path in sorted(root.rglob("*"))
            if path.is_file() and not path.is_symlink()
            and (suffixes is None or path.suffix in suffixes)}


def application_source_hashes(root: Path = ROOT) -> dict[str, str]:
    """Hash implementation sources only; no evaluation datasets or private files."""
    files: set[Path] = set()
    for directory, suffix in (("dispute_workflow", ".py"), ("banking_mcp", ".py"),
                              ("frontend/server", ".py"), ("pipeline", ".py"),
                              ("resources/prompts", ".yml"), ("resources/policies", ".md"),
                              ("config", ".yaml")):
        files.update((root / directory).glob("*" + suffix))
    for relative in ("scripts/qualify_dispute_app.py", "scripts/run_dispute.py",
                     "scripts/native_dispute_qualification.py", "scripts/native_dispute_qualification.ts",
                     "scripts/native_dispute_qualification.mjs", "contracts/tools.md",
                     "contracts/state_schema.md", "contracts/policy_engine.md", "resources/prompts/fallback_templates.yaml",
                     "pipeline/contracts.yaml",
                     "pipeline/contracts.yaml",
                     "requirements-dispute.txt", "requirements-pipeline.txt", "frontend/requirements.txt"):
        path = root / relative
        if path.is_file():
            files.add(path)
    return {path.relative_to(root).as_posix(): _digest(path.read_bytes()) for path in sorted(files)}


@dataclass(frozen=True)
class Fixture:
    """Private setup values. Do not serialize this object into the public report."""
    root: Path
    source: Path
    data: Path
    rates: Path
    rates_sha256: str
    signer: Path
    public_key: str
    subject_customers: dict[str, str]
    profiles: dict[str, dict[str, str]]
    targets: dict[str, dict[str, str]]
    demo_code: str
    service_token: str
    execution_token: str
    identifier_salt: bytes
    created_at: datetime
    source_hashes: dict[str, str]

    def hash_id(self, value: str) -> str:
        return hmac.new(self.identifier_salt, value.encode(), hashlib.sha256).hexdigest()


def _shift_value(value: str, offset: timedelta) -> str:
    # Historical account opening/registration and future card expiry stay valid;
    # only the prototype's event/report/update calendar moves with this run.
    if re.match(r"^2026-\d{2}-\d{2}(?:$|[ T])", value):
        shifted = date.fromisoformat(value[:10]) + offset
        return shifted.isoformat() + value[10:]
    return value


def build_fixture(private_dir: str | Path, *, now: datetime | None = None) -> Fixture:
    """Generate and publish current-date source, with explicit synthetic FX inputs.

    The directory must be fresh or empty. The pipeline reads only the new local
    source. No S3, source environment, organizer fixture or router dataset is used.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from pipeline.prototype_fixture import PERSONAS, write_prototype_source
    from pipeline.__main__ import main as pipeline_main

    root, now = Path(private_dir).resolve(), _utc(now)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError("fresh empty private qualification directory required")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    template, source, data = root / "generated-template", root / "source", root / "data"
    write_prototype_source(template)
    offset = now.date() - date(2026, 9, 27)
    targets: dict[str, dict[str, str]] = {}
    rate_keys: set[tuple[str, str]] = set()
    profile_by_customer = {p.customer_id: p.profile for p in PERSONAS}
    for original in sorted(template.rglob("*.csv")):
        relative = original.relative_to(template)
        with original.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            columns = list(reader.fieldnames or [])
            rows = [{key: _shift_value(value, offset) for key, value in row.items()}
                    for row in reader]
        parts = list(relative.parts)
        if len(parts) > 1:
            old_day = date(int(parts[1].split("=")[1]), int(parts[2].split("=")[1]),
                           int(parts[3].split("=")[1]))
            day = old_day + offset
            parts[1:4] = [f"year={day:%Y}", f"month={day:%m}", f"day={day:%d}"]
        if parts[0] == "products.csv":
            for row in rows:
                row["product_number"] = ("4000000000004381" if row["product_type"] == "Tarjeta Crédito"
                                         else "1000000000007729")
        if parts[0] == "transactions":
            for row in rows:
                # Rates below are fixture-author choices, never market FX claims.
                rate_keys.add((row["transaction_date"][:10], row["currency"]))
                if row["transaction_id"].endswith("-TX-014"):
                    targets[profile_by_customer[row["customer_id"]]] = dict(row)
        destination = source.joinpath(*parts)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        text = io.StringIO(newline="")
        writer = csv.DictWriter(text, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        _private_write(destination, text.getvalue().encode())
    if set(targets) != {p.profile for p in PERSONAS}:
        raise ValueError("generated approved targets unavailable")
    _private_write(source / "QUALIFICATION_SYNTHETIC.json", _json_bytes({
        "synthetic": True, "origin": "joined-dispute-qualification", "event_calendar_anchor": now.date().isoformat(),
        "prototype_anchor": "2026-09-27", "fx": "explicit fixture-author values, not market rates"}))
    rates = root / "event-rates.csv"
    rate_text = io.StringIO(newline="")
    writer = csv.writer(rate_text)
    writer.writerow(["date", "currency", "usd_rate"])
    synthetic_rates = {"MXN": "0.01", "COP": "0.00001", "ARS": "0.00001"}
    for day, currency in sorted(rate_keys):
        writer.writerow([day, currency, synthetic_rates[currency]])
    _private_write(rates, rate_text.getvalue().encode())
    # Pipeline diagnostic text stays private and is never printed into the report.
    pipeline_log = io.StringIO()
    with redirect_stdout(pipeline_log):
        status = pipeline_main(["run", "--source", str(source), "--out", str(data),
                                "--reports", str(root / "pipeline-reports")])
    _private_write(root / "pipeline.log", pipeline_log.getvalue().encode())
    if status != 0:
        raise ValueError("generated pipeline publication failed")
    signer_key = Ed25519PrivateKey.generate()
    signer = root / "frontend-signer.pem"
    _private_write(signer, signer_key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public = signer_key.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    salt = secrets.token_bytes(32)
    _private_write(root / "identifier-salt.bin", salt)
    profiles = {p.profile: {"customer_id": p.customer_id} for p in PERSONAS}
    subjects = {"qualification-" + p.profile: p.customer_id for p in PERSONAS}
    secrets_data = {"demo_code": secrets.token_urlsafe(32), "service_token": secrets.token_urlsafe(48),
                    "execution_token": secrets.token_urlsafe(48)}
    _private_write(root / "private-admission.json", _json_bytes(secrets_data))
    static = root / "static"
    _private_write(static / "index.html", b"<!doctype html><title>Private synthetic qualification</title>")
    # POSIX owner-only modes also cover files written by the pipeline. Windows
    # private-directory ACLs are supplied by the operator, not inferred from chmod.
    if os.name != "nt":
        for path in root.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
    return Fixture(root=root, source=source, data=data, rates=rates, rates_sha256=_digest(rates.read_bytes()),
        signer=signer, public_key=public, subject_customers=subjects, profiles=profiles, targets=targets,
        identifier_salt=salt, created_at=now, source_hashes=_tree_hashes(source), **secrets_data)


def _safe_observations(model: Any) -> list[dict[str, Any]]:
    result = []
    for observation in getattr(model, "observations", []):
        if not isinstance(observation, dict):
            continue
        safe = {}
        for key in _OBSERVATION_FIELDS:
            value = observation.get(key)
            if value is None:
                safe[key] = value
            elif type(value) in (int, float) and value >= 0 and math.isfinite(value):
                safe[key] = value
            elif isinstance(value, str) and (key == "stage" and value in _STAGES or
                  key == "status" and value in {"ok", "error", "timeout", "cancelled"} or
                  key == "response_id_kind" and value in {"codex", "chatcmpl", "claude", "unknown"}):
                safe[key] = value
            elif key == "model" and value == "model-dispute-native-model":
                safe[key] = value
            elif key == "response_model" and isinstance(value, str):
                safe["response_model_sha256"] = _digest(value.encode())
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cost_usd"):
            safe.setdefault(key, None)
        result.append(safe)
    return result


class CapturedModel:
    """Delegate native calls unchanged and retain bounded fictional output privately."""
    def __init__(self, model: Any, fixture: Fixture):
        self.model, self.fixture, self.captures = model, fixture, []

    def __getattr__(self, name: str):
        return getattr(self.model, name)

    def _capture(self, stage: str, output: str) -> None:
        if stage not in _STAGES or not isinstance(output, str) or len(output) > 32000:
            raise ValueError("bounded known stage output required")
        path = self.fixture.root / "private-stage-outputs" / (stage + "-" + secrets.token_hex(12) + ".json")
        _private_write(path, _json_bytes({"stage": stage, "output": output}))
        self.captures.append({"stage": stage, "output_hmac_sha256": self.fixture.hash_id(output)})

    async def __call__(self, stage: str, system: str, user: str):
        output = await self.model(stage, system, user)
        self._capture(stage, output)
        return output

    async def batch(self, requests):
        outputs = await self.model.batch(requests)
        for stage, output in outputs.items():
            self._capture(stage, output)
        return outputs


class ObservedWorkflow:
    """Read-only observation around the same application Workflow and model."""
    def __init__(self, workflow: Any, model: Any, records: list[dict[str, Any]], fixture: Fixture):
        self.workflow, self.model, self.records, self.fixture = workflow, model, records, fixture

    async def run(self, binding: Any, message: str, **kwargs: Any) -> dict[str, Any]:
        started, result = time.monotonic(), None
        observation = {"turn_hash": self.fixture.hash_id(str(kwargs.get("turn_id", ""))), "completed": False}
        try:
            result = await self.workflow.run(binding, message, **kwargs)
            workflow, runtime = result.get("workflow_state", {}), result.get("runtime", {})
            decision = workflow.get("policy_decision", {})
            from dispute_workflow.prompts import MODES
            mode, reason = decision.get("response_mode"), decision.get("reason_code")
            language = result.get("response", {}).get("language")
            observation.update(completed=True, response_mode=mode if mode in MODES else None,
                rule_ids=[item for item in decision.get("rule_ids", [])
                          if isinstance(item, str) and re.fullmatch(r"R[0-9]{1,3}", item)],
                reason_code=reason if reason in {"customer_request", "emergency", "missing_evidence", "high_risk",
                    "host_consent_verified", "receipt_verified", "exact_open_case", "out_of_policy"} else None,
                language=language if language in {"es", "pt"} else None,
                safe_fallback_used=runtime.get("safe_fallback_used", False),
                validation_errors=[code for code in result.get("turn", {}).get("validation_errors", [])
                    if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,80}", code)],
                validation_attempts=result.get("turn", {}).get("validation_attempts"),
                node_errors=[{key: item.get(key) for key in ("node", "code")}
                             for item in runtime.get("node_errors", []) if isinstance(item, dict)
                             and item.get("node") in _NODES and item.get("code") in {
                                 "model_error", "invalid_json", "schema", "timeout", "tool_error", "shape",
                                 "authorization_denied", "snapshot_changed", "source_unavailable"}],
                trace=[{key: item[key] for key in ("node", "latency_ms", "attempts") if key in item}
                       for item in result.get("trace", []) if isinstance(item, dict)
                       and item.get("turn_id") == kwargs.get("turn_id") and item.get("node") in _NODES])
            return result
        finally:
            observation.update(latency_ms=round((time.monotonic() - started) * 1000),
                               model_observations=_safe_observations(self.model),
                               stage_output_hashes=getattr(self.model, "captures", []))
            self.records.append(observation)


def build_application(fixture: Fixture, native_url: str, authority_dir: str | Path, *,
                      instance: str, records: list[dict[str, Any]], port_factory: Callable | None = None,
                      model_transport: Any = None, native_timeout_seconds: float = 90):
    """Use the actual root application builder, with observation-only wrapping.

    An injected port has NativeDisputePort's constructor signature and must invoke
    its supplied workflow factory; it is only for explicitly controlled tests.
    Returns ``(app, bank_service)``; callers must close the bank after app shutdown.
    """
    from banking_mcp.config import Config
    from frontend.server.config import Settings
    from scripts.run_dispute import application

    if not _SAFE_NAME.fullmatch(instance):
        raise ValueError("bounded instance name required")
    if not 0 < native_timeout_seconds <= 120 or not math.isfinite(native_timeout_seconds):
        raise ValueError("bounded native stage timeout required")
    if _tree_hashes(fixture.source) != fixture.source_hashes or _digest(fixture.rates.read_bytes()) != fixture.rates_sha256:
        raise ValueError("generated fixture changed before application admission")
    state = fixture.root / "instances" / instance
    settings = Settings(data_dir=fixture.data, state_dir=fixture.root / "unused-frontend-state",
        static_dir=fixture.root / "static", demo_code=fixture.demo_code, profiles=fixture.profiles,
        chat={"base_url": native_url, "model": "flow-Dispute", "execution_token": fixture.execution_token,
              "frontend_signing_key_file": str(fixture.signer), "frontend_kid": "qualification",
              "frontend_issuer": "qualification", "frontend_audience": "flujo-banking-ingress",
              "principal_customers": fixture.subject_customers, "action_enabled": True})
    coverage = int(fixture.created_at.timestamp()) - 172800
    bank_config = Config(data_dir=fixture.data, state_db=state / "bank.sqlite3",
        service_token=fixture.service_token, public_keys={"qualification": fixture.public_key},
        principal_customers=fixture.subject_customers, sandbox_report_coverage_start=coverage,
        event_rates_file=fixture.rates, event_rates_sha256=fixture.rates_sha256,
        ledger_continuity_approved=True)
    app, bank = application(settings, bank_config, state, native_url, Path(authority_dir),
        source_root=fixture.source, enable_simulated_intake=True)
    bank.store.attest_sandbox_coverage(coverage, "synthetic:joined-dispute-generated-ledger")
    # Capture the application's installed factory before create_app's lifespan
    # assigns it. This delegates to the exact NativeHostFactory used by runner.
    from scripts.run_dispute import NativeHostFactory
    native_factory = NativeHostFactory(state / "dispute-workflow.sqlite3", bank, native_url,
                                       authority_dir, source_root=fixture.source)
    from frontend.server.app import create_app
    from dispute_workflow.action_host import BankingActionHost
    from dataclasses import replace

    def observed_factory(repository, chat, profile, sid, expiry):
        port = native_factory(repository, chat, profile, sid, expiry)
        original_factory = port.workflow_factory
        def wrapped_factory(model):
            if model_transport is not None:
                model.transport = model_transport
            captured = CapturedModel(model, fixture)
            return ObservedWorkflow(original_factory(captured), captured, records, fixture)
        if port_factory is not None:
            return port_factory(wrapped_factory, native_url, authority_dir)
        port.workflow_factory = wrapped_factory
        port.timeout = native_timeout_seconds
        return port

    # create_app receives the same owner sources, durable store and action bridge
    # as application(); only its private workflow factory gains the observer.
    backend = BankingActionHost(bank, native_factory.store, source_root=fixture.source)
    app = create_app(replace(settings, state_dir=state,
        chat={**settings.chat, "mode": "dispute-host/v1", "ledger_generation": native_factory.ledger_generation}),
        dispute_factory=observed_factory, bank_backend=backend)
    return app, bank


@contextmanager
def serve_loopback(app: Any):
    """Run the real ASGI app on a private ephemeral loopback HTTP listener."""
    import uvicorn
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
        access_log=False, log_level="critical", lifespan="on"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("local application startup failed")
            time.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        if thread.is_alive():
            server.force_exit = True
            thread.join(timeout=5)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("local application shutdown incomplete")


class QualificationFailure(AssertionError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class AttemptRecorder:
    def __init__(self, records: list[dict[str, Any]], *, native: bool):
        self.turns, self.native = records, native
        self.attempts: list[dict[str, Any]] = []

    def request(self, client, name: str, method: str, path: str, *, status: int | tuple[int, ...] = 200,
                body: dict | None = None, check: Callable[[dict], bool] | None = None) -> dict:
        started, first_turn = time.monotonic(), len(self.turns)
        attempt = {"step": name, "method": method, "path": path, "passed": False}
        try:
            response = client.request(method, path, **({"json": body} if body is not None else {}))
            attempt["http_status"] = response.status_code
            if response.status_code not in ((status,) if isinstance(status, int) else status):
                raise QualificationFailure(name + ".http_status")
            value = response.json() if response.content else {}
            if not isinstance(value, dict) or check is not None and not check(value):
                raise QualificationFailure(name + ".expected_contract")
            if path == "/api/chat":
                turns = self.turns[first_turn:]
                if len(turns) != 1 or turns[0].get("completed") is not True:
                    raise QualificationFailure(name + ".workflow_observation")
                if self.native and not any(item.get("status") == "ok" for item in turns[0]["model_observations"]):
                    raise QualificationFailure(name + ".native_model_usage")
            attempt["passed"] = True
            return value
        except QualificationFailure as exc:
            attempt["failure_code"] = exc.code
            raise
        except Exception as exc:
            # HTTP/model exceptions may contain URLs, assertions or bodies. Only
            # their bounded class name belongs in the public result.
            attempt["failure_code"] = type(exc).__name__
            raise
        finally:
            attempt.update(latency_ms=round((time.monotonic() - started) * 1000),
                           workflow_turns=self.turns[first_turn:])
            self.attempts.append(attempt)


def _expect(condition: bool, code: str) -> None:
    if not condition:
        raise QualificationFailure(code)


def _case_count(bank: Any, customer: str) -> int:
    with bank.store.connect() as db:
        return db.execute("SELECT count(*) FROM sandbox_cases WHERE customer=?", (customer,)).fetchone()[0]


def _chat_contract(turns: list[dict], *, mode: str, language: str, reason: str | None = None) -> None:
    turn = turns[-1] if turns else {}
    _expect(turn.get("response_mode") == mode, "chat.policy_mode")
    _expect(turn.get("language") == language, "chat.language")
    _expect(turn.get("safe_fallback_used") is False, "chat.generator_fallback")
    if reason is not None:
        _expect(turn.get("reason_code") == reason, "chat.policy_reason")


def _intake_scenario(fixture, native_url, authority_dir, profile, language, *, port_factory, model_transport,
                     server_factory, request_timeout_seconds, native_timeout_seconds):
    import httpx
    turns: list[dict] = []
    attempts = AttemptRecorder(turns, native=port_factory is None and model_transport is None)
    instance, target = "intake-" + language, fixture.targets[profile]
    customer, reference, receipt, pending, cookies = fixture.profiles[profile]["customer_id"], None, None, None, None
    outcome = {"scenario": instance, "language": language, "synthetic_expected": "CONFIRM_ACTION then ACTION_DONE",
               "passed": False, "attempts": attempts.attempts}
    try:
        app, bank = build_application(fixture, native_url, authority_dir, instance=instance,
            records=turns, port_factory=port_factory, model_transport=model_transport,
            native_timeout_seconds=native_timeout_seconds)
        try:
            with server_factory(app) as url, httpx.Client(base_url=url, timeout=request_timeout_seconds, trust_env=False,
                    follow_redirects=False, headers={"Origin": url}) as client:
                attempts.request(client, "login", "POST", "/api/auth/login",
                    body={"profile": profile, "code": fixture.demo_code})
                # Resolve through the public owner-bound list, not raw fixture IDs.
                listed = attempts.request(client, "owned_transactions", "GET", "/api/transactions")
                matches = [row for row in listed.get("transactions", [])
                           if row.get("occurred_at", "")[:10] == target["transaction_date"][:10]
                           and row.get("merchant") == target["merchant_name"]
                           and str(row.get("currency")) == target["currency"]
                           and row.get("type") == "Purchase"]
                _expect(len(matches) == 1, "selection.unique_owned_target")
                reference = matches[0]["reference"]
                outcome["target_reference_hash"] = fixture.hash_id(reference)
                message = ((f"No reconozco la compra de {target['amount']} {target['currency']} del "
                            f"{target['transaction_date'][:10]} en mi tarjeta. Quiero revisarla.") if language == "es" else
                           (f"Não reconheço a compra de {target['amount']} {target['currency']} de "
                            f"{target['transaction_date'][:10]} no meu cartão. Quero verificar."))
                attempts.request(client, "selected_dispute", "POST", "/api/chat",
                    body={"message": message, "transaction_reference": reference},
                    check=lambda value: value.get("mode") == "dispute")
                _chat_contract(turns, mode="CONFIRM_ACTION", language=language)
                prepared = attempts.request(client, "prepare", "POST", "/api/action/prepare",
                    body={"transaction_reference": reference, "language": language},
                    check=lambda value: value.get("state") == "pending_confirmation")
                pending = prepared["pending_handle"]
                outcome["pending_handle_hash"] = fixture.hash_id(pending)
                attempts.request(client, "reject_false_consent", "POST", "/api/action/confirm", status=422,
                    body={"transaction_reference": reference, "pending_handle": pending,
                          "confirmed": False, "language": language})
                _expect(_case_count(bank, customer) == 0, "consent.no_case_before_explicit_true")
                confirmed = attempts.request(client, "confirm", "POST", "/api/action/confirm",
                    body={"transaction_reference": reference, "pending_handle": pending,
                          "confirmed": True, "language": language},
                    check=lambda value: value.get("state") == "intake_verified")
                receipt = confirmed["receipt"]
                _expect(receipt.get("simulated") is True and receipt.get("kind") == "simulated_intake",
                        "receipt.explicit_simulation")
                _expect(receipt.get("snapshot") == bank.repository.snapshot().id, "receipt.snapshot")
                _expect(receipt.get("transaction", {}).get("amount") == f"{float(target['amount']):.2f}" and
                        receipt.get("transaction", {}).get("currency") == target["currency"], "receipt.source_facts")
                _expect(_case_count(bank, customer) == 1, "receipt.exactly_one_case")
                with bank.store.connect() as db:
                    saved_case = db.execute("SELECT id,customer,transaction_id,snapshot FROM sandbox_cases WHERE id=?",
                                            (receipt["id"],)).fetchone()
                    saved_receipt = db.execute("SELECT receipt_json FROM sandbox_case_receipts WHERE case_id=?",
                                               (receipt["id"],)).fetchone()
                _expect(saved_case is not None and tuple(saved_case) == (receipt["id"], customer,
                        target["transaction_id"], receipt["snapshot"]), "receipt.saved_owner_target_snapshot")
                _expect(saved_receipt is not None and json.loads(saved_receipt[0]) == receipt,
                        "receipt.saved_readback")
                outcome.update(receipt_id_hash=fixture.hash_id(receipt["id"]),
                               snapshot_id_hash=fixture.hash_id(receipt["snapshot"]))
                cookies = httpx.Cookies(client.cookies)
        finally:
            bank.close()
        # Reconstruct every application service from the same durable state.
        app, bank = build_application(fixture, native_url, authority_dir, instance=instance,
            records=turns, port_factory=port_factory, model_transport=model_transport,
            native_timeout_seconds=native_timeout_seconds)
        try:
            with server_factory(app) as url, httpx.Client(base_url=url, cookies=cookies, timeout=request_timeout_seconds,
                    trust_env=False, follow_redirects=False, headers={"Origin": url}) as client:
                restored = attempts.request(client, "receipt_after_restart", "GET",
                    "/api/action/status?language=" + language,
                    check=lambda value: value.get("state") == "intake_verified" and value.get("receipt") == receipt)
                followup = "¿Cuál es el estado de esta solicitud?" if language == "es" else "Qual é o estado desta solicitação?"
                report = attempts.request(client, "native_receipt_followup", "POST", "/api/chat",
                    body={"message": followup}, check=lambda value: value.get("mode") == "dispute")
                _chat_contract(turns, mode="ACTION_DONE", language=language)
                _expect(receipt["id"] in report.get("reply", ""), "followup.authoritative_receipt_id")
                replay = attempts.request(client, "confirm_replay", "POST", "/api/action/confirm",
                    body={"transaction_reference": reference, "pending_handle": pending,
                          "confirmed": True, "language": language},
                    check=lambda value: value.get("state") == "intake_verified" and value.get("receipt") == receipt)
                _expect(replay.get("receipt") == restored.get("receipt") and _case_count(bank, customer) == 1,
                        "replay.durable_exactly_one_case")
                saved_cookies = httpx.Cookies(client.cookies)
                attempts.request(client, "logout_revokes", "POST", "/api/auth/logout", status=204, body={})
                client.cookies = saved_cookies
                attempts.request(client, "revoked_cookie_cannot_read_receipt", "GET", "/api/action/status", status=401)
                attempts.request(client, "revoked_cookie_cannot_replay", "POST", "/api/action/confirm", status=401,
                    body={"transaction_reference": reference, "pending_handle": pending,
                          "confirmed": True, "language": language})
                _expect(_case_count(bank, customer) == 1, "revocation.no_new_case")
                outcome["passed"] = True
        finally:
            bank.close()
    except Exception as exc:
        outcome["failure_code"] = exc.code if isinstance(exc, QualificationFailure) else type(exc).__name__
    return outcome


def _handoff_scenario(fixture, native_url, authority_dir, *, emergency, port_factory, model_transport,
                      server_factory, request_timeout_seconds, native_timeout_seconds):
    import httpx
    turns: list[dict] = []
    attempts = AttemptRecorder(turns, native=port_factory is None and model_transport is None)
    reason = "emergency" if emergency else "customer_request"
    language = "pt" if emergency else "es"
    instance = "handoff-" + reason
    outcome = {"scenario": instance, "language": language, "synthetic_expected": "HANDOFF: " + reason,
               "passed": False, "attempts": attempts.attempts}
    try:
        app, bank = build_application(fixture, native_url, authority_dir, instance=instance,
            records=turns, port_factory=port_factory, model_transport=model_transport,
            native_timeout_seconds=native_timeout_seconds)
        try:
            with server_factory(app) as url, httpx.Client(base_url=url, timeout=request_timeout_seconds, trust_env=False,
                    follow_redirects=False, headers={"Origin": url}) as client:
                attempts.request(client, "login", "POST", "/api/auth/login",
                    body={"profile": "argentina", "code": fixture.demo_code})
                message = ("É uma emergência, estou em perigo agora e preciso falar com um atendente humano."
                           if emergency else "Quiero hablar con un asesor humano para revisar mi solicitud.")
                attempts.request(client, "native_handoff_request", "POST", "/api/chat", body={"message": message},
                                 check=lambda value: value.get("mode") == "dispute")
                _chat_contract(turns, mode="HANDOFF", language=language, reason=reason)
                handoff = attempts.request(client, "explicit_handoff", "POST", "/api/action/handoff",
                    body={"reason": reason, "language": language},
                    check=lambda value: value.get("state") == "handoff_verified")
                packet = handoff.get("handoff", {})
                _expect(packet.get("human_responded") is False and packet.get("reason") == reason,
                        "handoff.no_human_adjudication")
                outcome["handoff_id_hash"] = fixture.hash_id(packet["id"])
                _expect(_case_count(bank, fixture.profiles["argentina"]["customer_id"]) == 0,
                        "handoff.no_intake_case")
                outcome["passed"] = True
        finally:
            bank.close()
    except Exception as exc:
        outcome["failure_code"] = exc.code if isinstance(exc, QualificationFailure) else type(exc).__name__
    return outcome


def run_qualification(fixture: Fixture, native_url: str, authority_dir: str | Path, *,
                      port_factory: Callable | None = None, model_transport: Any = None,
                      server_factory: Callable = serve_loopback,
                      scenarios: tuple[str, ...] = ("intake-es", "intake-pt", "human", "emergency"),
                      request_timeout_seconds: float = 600, native_timeout_seconds: float = 90) -> dict:
    """Run actual HTTP customer paths; default language calls use NativeDisputePort.

    Controlled ports are permitted for tests, but never establish native/provider
    acceptance. A failing scenario is retained and does not erase other attempts.
    """
    allowed = {"intake-es", "intake-pt", "human", "emergency"}
    if not scenarios or set(scenarios) - allowed or len(set(scenarios)) != len(scenarios):
        raise ValueError("unique explicit qualification scenarios required")
    if not 0 < request_timeout_seconds <= 900 or not math.isfinite(request_timeout_seconds):
        raise ValueError("bounded local HTTP request timeout required")
    if not 0 < native_timeout_seconds <= 120 or not math.isfinite(native_timeout_seconds):
        raise ValueError("bounded native stage timeout required")
    before, started = application_source_hashes(), _utc()
    authority = Path(authority_dir).resolve()
    # Do not record admissions, owner ledger, tokens, profile contents or paths.
    profile_hash = _digest((authority / "native-profile.json").read_bytes())
    results = []
    for scenario in scenarios:
        if scenario.startswith("intake-"):
            language = scenario[-2:]
            results.append(_intake_scenario(fixture, native_url, authority,
                "mexico" if language == "es" else "colombia", language,
                port_factory=port_factory, model_transport=model_transport, server_factory=server_factory,
                request_timeout_seconds=request_timeout_seconds, native_timeout_seconds=native_timeout_seconds))
        else:
            results.append(_handoff_scenario(fixture, native_url, authority, emergency=scenario == "emergency",
                port_factory=port_factory, model_transport=model_transport, server_factory=server_factory,
                request_timeout_seconds=request_timeout_seconds, native_timeout_seconds=native_timeout_seconds))
    after, finished = application_source_hashes(), _utc()
    generated_after = _tree_hashes(fixture.source)
    stable = before == after and fixture.source_hashes == generated_after and fixture.rates_sha256 == _digest(fixture.rates.read_bytes())
    scripted = port_factory is not None or model_transport is not None
    observations = [observation for result in results for attempt in result["attempts"]
                    for turn in attempt["workflow_turns"] for observation in turn.get("model_observations", [])]
    known_tokens = [observation["total_tokens"] for observation in observations
                    if observation.get("total_tokens") is not None]
    known_costs = [observation["cost_usd"] for observation in observations if observation.get("cost_usd") is not None]
    return {"schema": SCHEMA, "synthetic": True, "human_adjudicated": False,
        "execution_mode": "scripted_offline" if scripted else "native_port_http",
        "native_execution_verified": False,
        "native_port_invoked": not scripted and any(attempt["workflow_turns"]
            for result in results for attempt in result["attempts"]),
        "model_call_observed": any(
            observation.get("status") == "ok" for result in results for attempt in result["attempts"]
            for turn in attempt["workflow_turns"] for observation in turn.get("model_observations", [])),
        "started_at": started.isoformat(), "finished_at": finished.isoformat(),
        "latency_ms": round((finished - started).total_seconds() * 1000),
        "fixture_event_calendar_anchor": fixture.created_at.date().isoformat(),
        "application_sources_before": before, "application_sources_after": after,
        "generated_source_before": fixture.source_hashes, "generated_source_after": generated_after,
        "event_rates_sha256": fixture.rates_sha256, "native_profile_sha256": profile_hash,
        "source_stable": stable, "passed": stable and all(result["passed"] for result in results),
        "scenario_count": len(results), "passed_scenarios": sum(result["passed"] for result in results),
        "model_attempt_count": len(observations),
        "usage": {"total_tokens": sum(known_tokens) if observations and len(known_tokens) == len(observations) else None,
                  "cost_usd": sum(known_costs) if observations and len(known_costs) == len(observations) else None,
                  "attempts_with_unknown_tokens": len(observations) - len(known_tokens),
                  "attempts_with_unknown_cost": len(observations) - len(known_costs),
                  "failed_model_attempts": sum(item.get("status") != "ok" for item in observations)},
        "timeouts": {"local_http_request_seconds": request_timeout_seconds, "native_stage_seconds": native_timeout_seconds},
        "results": results,
        "limits": ["All people, customer records, rates and ledger coverage are explicit generated fiction.",
            "Application prompts and policy are the actual versioned implementation sources listed by their hashes.",
            "Expected labels are scenario-author assertions; no human semantic adjudication occurred.",
            "This report covers selected local HTTP paths and observed calls through the configured model port.",
            "It does not establish deployment, shared worker activation, real banking writes, or general model accuracy.",
            "Unavailable provider usage remains null; provider cost is not inferred from token counts.",
            "Scripted ports/transports do not establish native execution.",
            "Native execution verification requires separate retained-worker installed-manifest and callback evidence."]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir-private", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-url")
    parser.add_argument("--native-authority-dir", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--cases", default="intake-es,intake-pt,human,emergency",
                        help="comma-separated intake-es,intake-pt,human,emergency")
    parser.add_argument("--request-timeout-seconds", type=float, default=600)
    parser.add_argument("--native-timeout-seconds", type=float, default=90)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("new public report output required")
    if not args.prepare_only and (not args.native_url or not args.native_authority_dir):
        parser.error("installed isolated native URL and authority directory required")
    fixture = build_fixture(args.workdir_private)
    if args.prepare_only:
        report = {"schema": SCHEMA, "synthetic": True, "human_adjudicated": False,
            "execution_mode": "prepare_only", "native_execution_verified": False,
            "native_port_invoked": False, "model_call_observed": False, "passed": None,
            "scenario_count": 0, "fixture_event_calendar_anchor": fixture.created_at.date().isoformat(),
            "application_sources_before": application_source_hashes(), "generated_source_before": fixture.source_hashes,
            "event_rates_sha256": fixture.rates_sha256,
            "limits": ["Fixture publication only; no native worker, provider or HTTP qualification was executed."]}
    else:
        report = run_qualification(fixture, args.native_url, args.native_authority_dir,
            scenarios=tuple(args.cases.split(",")), request_timeout_seconds=args.request_timeout_seconds,
            native_timeout_seconds=args.native_timeout_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as output:
        output.write(_json_bytes(report))
    print(json.dumps({"schema": SCHEMA, "execution_mode": report["execution_mode"],
                      "passed": report["passed"], "scenario_count": report["scenario_count"]}))
    return 0 if args.prepare_only or report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
