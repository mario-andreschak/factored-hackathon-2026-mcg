"""Held, instrumented API assembly. Imports launch nothing and create no state.

Runtime construction uses original FLUJO launcher/native snapshot restore and
bank71 stdio. Frontend production modules and reviewed helper blobs stay intact.
Only private trusted fixture code receives cookies, keys, scopes or fault gates.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import signal
import subprocess
import threading
import time
import uuid
import zipfile

from contract import require, require_runtime_release, strict_json
from dataset import scoped_path
from deterministic_provider import FixtureProvider
from observer_adapter import (LedgerAdapter, canonical, one, read_db, token_from_cookie, transport_counts,
                              UUID4, complete_bootstrap_log, verify_bootstrap_records)

FIXTURE_ROOT = Path("/opt/integration/fixture")
FRONT_PORT, WORKER_PORT, MODEL_PORT, SANDBOX_PORT = 8200, 4200, 8202, 8203
PHASES = {"stock-missing-coverage", "stock-prepare-response-loss", "authored-empty-history",
          "authored-confirm-response-loss"}


def write_private(path: Path, value, *, raw=False):
    with path.open("xb") as stream:
        stream.write(value if raw else json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
    path.chmod(0o400)


@dataclass(repr=False)
class Context:
    actor: str
    scope: object
    observer: object
    conversation: str
    reference: str | None


class Provider:
    def __init__(self, root: Path, *, phase: str):
        require(phase in PHASES and root.is_absolute(), "fixture_phase_invalid")
        self.root, self.phase = root, phase
        self.frontend_origin = "http://127.0.0.1:" + str(FRONT_PORT)
        self.worker_origin = "http://127.0.0.1:" + str(WORKER_PORT)
        self.contexts = {}
        self.latest = {}
        self.fault = None
        self.worker = self.front_thread = self.front_server = self.model = None
        self.loop = self.app = None
        self.generations = set()
        self.bootstrap_receipts = {}  # private minimal validated projections only

    def _guard(self):
        return require_runtime_release(dict(os.environ))

    def _bank_env(self):
        env = {key: os.environ[key] for key in ("GITHUB_ACTIONS", "RUNNER_ENVIRONMENT", "RUNNER_OS",
                                               "GITHUB_REPOSITORY", "GITHUB_SHA", "PATH") if key in os.environ}
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1",
                   PYTHONPATH="/opt/banking-mcp:/opt/integration/harness:/opt/integration/fixture",
                   SYNTHETIC_BANK_SERVICE_TOKEN=self.bank_token, HOME=str(self.root / "home"),
                   TMPDIR=str(self.root / "temp"))
        return env

    def start(self):
        self._guard()
        scoped_path(self.root, exists=False)
        require(not self.root.exists(), "fresh_phase_required")
        self.root.mkdir(mode=0o700)
        for name in ("home", "temp", "front-state", "static", "flujo-data", "adapter-state"):
            (self.root / name).mkdir(mode=0o700)
        self.bank_token = secrets.token_urlsafe(48)
        self.execution_token = secrets.token_urlsafe(48)
        self.control_token = secrets.token_urlsafe(48)
        self.demo_code = secrets.token_urlsafe(32)
        self.model_token = secrets.token_urlsafe(48)
        self.attested = self.phase.startswith("authored-")
        subprocess.run(["/opt/banking-mcp/.venv/bin/python", str(FIXTURE_ROOT / "fixture_setup.py"),
                        str(self.root), "attested" if self.attested else "stock"], cwd="/opt/banking-mcp",
                       env=self._bank_env(), check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.metadata = strict_json((self.root / "setup-readback.json").read_bytes())
        self.ledger = LedgerAdapter(self.root, self.metadata)
        self._configure()
        self.model = FixtureProvider(MODEL_PORT, self.model_token)
        self.model.start()
        self._start_worker()
        self._start_frontend()
        # Initial ordinary runFlow evidence for the phase, followed by a fresh
        # bootstrap for EACH later browser login. Never seed conversations.
        from scenarios import Browser
        browser = Browser(self.frontend_origin)
        code, result = browser.request("POST", "/api/auth/login", self.credentials("es"))
        require(code == 200 and result.get("authenticated") is True, "initial_fixture_login")
        self.bind_selection("es", browser.cookie_header(), "normal")
        require(self.bootstrap_receipts, "ordinary_flow_bootstrap_not_verified")

    def _configure(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        template = strict_json((FIXTURE_ROOT / "policy-template.json").read_bytes())
        self.template = template
        self.front_key = Ed25519PrivateKey.generate()
        bank_key = Ed25519PrivateKey.generate()
        def public(key):
            return key.public_key().public_bytes(serialization.Encoding.PEM,
                                                 serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        def private(key):
            return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption())
        write_private(self.root / "frontend.pem", private(self.front_key), raw=True)
        write_private(self.root / "bank.pem", private(bank_key), raw=True)
        self.graph = strict_json((FIXTURE_ROOT / "flow-snapshot.json").read_bytes())
        self.model_name = "flow-" + self.graph["name"]
        # Mirrors canonicalJson/normalizeBehaviorRulesInput for this ASCII-only
        # graph without aliases, floats or undefined values. Fixed authored 0
        # graph timestamps prevent FlowService's mtime backfill changing its hash.
        self.graph_hash = hashlib.sha256(json.dumps(self.graph, sort_keys=True, separators=(",", ":"),
                                                    ensure_ascii=False).encode()).hexdigest()
        self.deployment = "synthetic-" + uuid.uuid4().hex
        profiles = template["profiles"]
        subjects = {value["customer"]: value["customer"] for value in profiles.values()}
        bank_config = {"mode": "delegated", "data_dir": str(self.root / "dataset"),
                       "state_db": str(self.ledger.bank), "service_token": self.bank_token,
                       "issuer": template["bankIssuer"], "audience": template["bankAudience"],
                       "public_keys": {template["bankKeyId"]: public(bank_key)}, "principal_customers": subjects,
                       "synthetic_evidence_file": str(self.root / "risk-evidence.json")}
        if self.attested:
            bank_config["sandbox_report_coverage_start"] = self.metadata["coverage_start"]
        self.bank_config_path = self.root / "bank.json"
        write_private(self.bank_config_path, bank_config)
        fields = ("workspace", "frontendIssuer", "frontendAudience", "bankIssuer", "bankAudience", "bankKeyId",
                  "bankServerName", "bankCommand", "bankCwd", "maxActiveRuns", "maxQueuedRuns",
                  "maxPendingPerSubject", "maxQueueWaitSeconds", "maxRunSeconds")
        self.policy = {key: template[key] for key in fields}
        self.policy.update(deploymentId=self.deployment, executionToken=self.execution_token,
                           stateDir=str(self.root / "adapter-state"),
                           frontendKeys={template["frontendKeyId"]: public(self.front_key)},
                           bankSigningKeyFile=str(self.root / "bank.pem"), bankConfigFile=str(self.bank_config_path),
                           flowId=self.graph["id"], graphHash=self.graph_hash)
        write_private(self.root / "policy.json", self.policy)
        self.chat_config = {"base_url": self.worker_origin, "model": self.model_name, "action_enabled": True,
                            "execution_token": self.execution_token, "frontend_issuer": template["frontendIssuer"],
                            "frontend_kid": template["frontendKeyId"], "frontend_audience": template["frontendAudience"],
                            "frontend_signing_key_file": str(self.root / "frontend.pem"), "principal_customers": subjects}
        server = {"name": template["bankServerName"], "transport": "stdio", "command": template["bankCommand"],
                  "args": ["-m", "banking_mcp", "serve", "--config", str(self.bank_config_path), "--transport", "stdio"],
                  "cwd": template["bankCwd"], "rootPath": template["bankCwd"], "env": {}, "disabled": False,
                  "enableMcpApps": False, "enableMcpSkills": False, "exposeAsMcpServer": False}
        workspace_root = self.root / "flujo-data/workspaces" / template["workspace"]
        files = {"db/models.json": [{"id": "synthetic-fixture-provider", "name": "synthetic-fixture-model",
                  "provider": "openai", "adapter": "openai", "ApiKey": self.model_token,
                  "baseUrl": "http://127.0.0.1:" + str(MODEL_PORT) + "/v1", "supportsTools": True}],
                 "db/flows/" + self.graph["id"] + ".json": self.graph,
                 "db/mcp_servers.json": {server["name"]: server},
                 "db/speech_settings.json": {"telemetry": {"enabled": False, "notifyDaily": False},
                     "experimental": {"compactionEnabled": False, "snapshotsEnabled": False}},
                 ".workspace.json": {"roots": []}}
        members = {name: json.dumps(value, separators=(",", ":")).encode() for name, value in files.items()}
        package = strict_json(Path("/app/package.json").read_bytes())
        manifest = {"formatVersion": 2, "layoutVersion": 2, "workspace": template["workspace"],
                    "externalRootsIncluded": False, "source": {"version": package["version"], "platform": "linux"},
                    "subtrees": ["db", "mcp-servers", "userdata", "snapshots", "screenshots", "recordings",
                                 "browser-profile", "bash-utils", "artifacts"],
                    "files": [{"path": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                              for name, raw in sorted(members.items())],
                    "runtime": {"codexAuth": "none", "encryption": "default", "mcpTransfer": {
                        "formatVersion": 1, "sourceWorkspaceRoot": str(workspace_root), "servers": []}}}
        # Native stock restore accepts an unencrypted private ZIP. It is runtime
        # state in tmpfs, never the published source bundle. The empty transfer
        # plan installs nothing: banking launch is the existing image's absolute
        # registration, with exact argv/cwd/env guarded by stock authority.ts.
        self.archive = self.root / "worker-snapshot.zip"
        with zipfile.ZipFile(self.archive, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in sorted(members.items()):
                archive.writestr(name, raw)
            archive.writestr("snapshot-manifest.json", json.dumps(manifest, separators=(",", ":")))
        self.archive.chmod(0o400)
        self.archive_sha = hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def _start_worker(self):
        self._guard()
        generation = uuid.uuid4().hex
        self.generations.add(generation)
        env = self._bank_env()
        env.pop("SYNTHETIC_BANK_SERVICE_TOKEN")
        env.update(NODE_ENV="production", NEXT_TELEMETRY_DISABLED="1", FLUJO_CONTAINER="1", FLUJO_APP_ROOT="/app",
                   FLUJO_WORKER_MODE="1", FLUJO_WORKER_SNAPSHOT=str(self.archive),
                   FLUJO_WORKER_SNAPSHOT_SHA256=self.archive_sha, FLUJO_SNAPSHOT_CONTROL_TOKEN=self.control_token,
                   FLUJO_BANKING_CONFIG=str(self.root / "policy.json"), FLUJO_DATA_DIR=str(self.root / "flujo-data"),
                   FLUJO_PORT=str(WORKER_PORT), FLUJO_BASE_URL=self.worker_origin, FLUJO_EXPOSURE_MODE="localhost",
                   FLUJO_MCP_APP_SANDBOX_PORT=str(SANDBOX_PORT), FLUJO_MCP_APP_SANDBOX_HOST="127.0.0.1",
                   FLUJO_BUILD_REVISION="51ff39fc5bac84cbbb49bbd2b21b5ab89de8b14b",
                   NODE_OPTIONS="--require=" + str(FIXTURE_ROOT / "dispatch_observer.cjs"),
                   SYNTHETIC_OBSERVER_ROOT=str(self.root), SYNTHETIC_OBSERVER_GENERATION=generation,
                   SYNTHETIC_BANK_CONFIG=str(self.bank_config_path),
                   SYNTHETIC_LOOPBACK_PORTS=",".join(map(str, (FRONT_PORT, WORKER_PORT, MODEL_PORT, SANDBOX_PORT))))
        self.worker = subprocess.Popen(["node", "/app/scripts/launch-next.mjs", "start", "-p", str(WORKER_PORT),
                                        "-H", "127.0.0.1"], cwd="/app", env=env, start_new_session=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._wait(lambda: self._private_http(self.worker_origin, "GET", "/api/worker/status",
                                             headers={"Authorization": "Bearer " + self.control_token}),
                   lambda status, body: status == 200 and body.get("state") == "ready", timeout=120)

    def _start_frontend(self):
        self._guard()
        from frontend.server.app import create_app
        from frontend.server.config import Settings
        import uvicorn
        settings = Settings(data_dir=self.root / "dataset", state_dir=self.root / "front-state",
                            static_dir=self.root / "static", demo_code=self.demo_code, auth_mode="demo",
                            public_origin=self.frontend_origin, chat=self.chat_config,
                            profiles={value["profile"]: {"customer_id": value["customer"]}
                                      for value in self.template["profiles"].values()})
        app = create_app(settings)
        original_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(application):
            async with original_lifespan(application):
                self.loop, self.app = asyncio.get_running_loop(), application
                self._attach_fault()  # retain original service used by revocation worker
                yield
        app.router.lifespan_context = lifespan
        self.front_server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=FRONT_PORT,
                                                        access_log=False, log_config=None, log_level="critical"))
        self.front_thread = threading.Thread(target=self.front_server.run, daemon=True)
        self.front_thread.start()
        self._wait(lambda: self._private_http(self.frontend_origin, "GET", "/healthz"),
                   lambda status, _: status == 200, timeout=30)

    def _wait(self, request, accepted, *, timeout):
        import httpx
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.worker is not None:
                require(self.worker.poll() is None, "fixture_worker_exited")
            try:
                if accepted(*request()):
                    return
            except (OSError, TimeoutError, httpx.TransportError):
                pass
            time.sleep(0.2)
        require(False, "fixture_startup_timeout")

    def _private_http(self, origin, method, path, body=None, headers=None):
        self._guard()
        import httpx
        require(origin in {self.frontend_origin, self.worker_origin}, "fixed_fixture_origin")
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=60) as client:
            response = client.request(method, origin + path, json=body, headers={"Origin": origin, **(headers or {})})
        require(len(response.content) <= 4 * 1024 * 1024, "fixture_http_limit")
        return response.status_code, strict_json(response.content) if response.content else {}

    def credentials(self, actor):
        self._guard()
        require(actor in {"es", "pt"}, "fixture_actor")
        return {"profile": self.template["profiles"][actor]["profile"], "code": self.demo_code}

    def bind_selection(self, actor, cookie, charge):
        require(charge == "normal", "unreviewed_fixture_charge")
        return self._bind(actor, cookie, selected=True).reference

    def bind_general(self, actor, cookie):
        self._bind(actor, cookie, selected=False)

    def _bind(self, actor, cookie, *, selected):
        self._guard()
        from frontend_helpers.frontend_fault import FixtureScope
        from frontend_helpers.frontend_observers import (GeneratedFixturePaths, FrontendObservers,
            read_login_session, frontend_owner, bank_session_id)
        require(actor in {"es", "pt"}, "fixture_actor")
        profile = self.template["profiles"][actor]
        paths = GeneratedFixturePaths(self.root, self.root / "synthetic_provenance.json",
                    self.root / "front-state/frontend.sqlite3", self.root / "front-state/frontend-chat.sqlite3", self.ledger.bank)
        session = read_login_session(paths, cookie=token_from_cookie(cookie), expected_profile=profile["profile"],
                    expected_customer=profile["customer"], snapshot=self.metadata["build_id"],
                    source_fingerprint=self.metadata["source_fingerprint"])
        reference = None
        if selected:
            code, overview = self._private_http(self.frontend_origin, "GET", "/api/overview", headers={"Cookie": cookie})
            require(code == 200, "owned_overview_failed")
            candidates = []
            for row in overview.get("transactions", []):
                target = self.app.state.repository.action_target(profile["profile"], row.get("reference"))
                if target is not None and target["transaction_id"] == profile["transaction"]:
                    require(target["snapshot"] == self.metadata["build_id"], "selection_snapshot_changed")
                    candidates.append(row["reference"])
            require(len(candidates) == 1, "owned_normal_selection_required")
            reference = candidates[0]
        body = {"message": "Consulta sintética." if actor == "es" else "Consulta sintética em português."}
        if reference is not None:
            body["transaction_reference"] = reference
        with read_db(paths.frontend_chat_db) as db:
            require(db.execute("SELECT count(*) FROM chat_sessions WHERE session_id=?", (session.session_id,)).fetchone()[0] == 0,
                    "fresh_bootstrap_session_required")
        with self.model.lock:
            issued_before = set(self.model.accepted_routing)
        code, reply = self._private_http(self.frontend_origin, "POST", "/api/chat/messages", body, {"Cookie": cookie})
        require(code == 200 and reply.get("mode") == "flujo" and reply.get("status") == "completed",
                "per_session_completed_ordinary_chat_bootstrap")
        with read_db(paths.frontend_chat_db) as db:
            row = one(db, "SELECT * FROM chat_sessions WHERE session_id=?", (session.session_id,))
        owner = frontend_owner(self.template["frontendIssuer"], profile["customer"], self.model_name)
        require(row["owner"] == owner and row["subject"] == row["customer_id"] == profile["customer"]
                and row["expires"] == session.session_exp and row["revoked"] == 0
                and isinstance(row["conversation_id"], str), "actual_chat_session_binding")
        self._verify_bootstrap(session.session_id, row["conversation_id"], issued_before,
                               reply=reply, subject=profile["customer"])
        scope = FixtureScope(fixture_id=self.phase, source_fingerprint=self.metadata["source_fingerprint"],
                    profile_id=profile["profile"], worker_origin=self.worker_origin, issuer=self.template["frontendIssuer"],
                    subject=profile["customer"], frontend_session_id=session.session_id, frontend_session_exp=session.session_exp,
                    frontend_model=self.model_name, frontend_owner=owner, bank_deployment_id=self.deployment,
                    bank_session_id=bank_session_id(self.deployment, self.template["frontendIssuer"], session.session_id),
                    customer_id=profile["customer"], transaction_id=profile["transaction"], snapshot=self.metadata["build_id"],
                    facts_sha256=canonical(self.metadata["facts"][actor]), ledger_generation=self.metadata["generation"],
                    expected_outcome="pending_confirmation" if self.attested else "handoff_verified")
        observer = FrontendObservers(paths, scope, {self.template["frontendKeyId"]: self.front_key.public_key()})
        if self.attested:
            history = strict_json((self.root / "bank-state/coverage-history.json").read_bytes())
            readback = strict_json((self.root / "bank-state/coverage-readback.json").read_bytes())
            observer.verify_attested_phase(fixture_artifact=self.root / "bank-state/coverage-history.json",
                fixture_sha256=readback["history_sha256"], expected_generation=self.metadata["generation"],
                expected_coverage_start=self.metadata["coverage_start"], declared_closed_interval_end=history["interval"]["end"],
                expected_provenance=readback["provenance"])
        context = Context(actor, scope, observer, row["conversation_id"], reference)
        self.contexts[session.session_id] = context
        self.latest[actor] = context
        return context

    def _verify_bootstrap(self, session_id, conversation, issued_before, *, reply, subject):
        self._guard()
        require(isinstance(conversation, str) and re.fullmatch(UUID4, conversation) is not None,
                "bootstrap_conversation_invalid")
        workspace = self.root / "flujo-data/workspaces" / self.template["workspace"] / "db"
        state_path = workspace / "conversations" / (conversation + ".json")
        log_path = workspace / "conversation-logs" / (conversation + ".jsonl")
        # Exact stock BankingStore.filename('owners', conversation), read only.
        owner_path = self.root / "adapter-state" / hashlib.sha256(self.deployment.encode()).hexdigest() / "owners" / (
            hashlib.sha256(conversation.encode()).hexdigest() + ".json")
        expected_owner = {"issuer": self.template["frontendIssuer"], "subject": subject, "graph": self.graph_hash,
                          "deployment": self.deployment, "workspace": self.template["workspace"]}
        deadline = time.monotonic() + 3
        # Stock log appends can still be flushing after the synchronous response.
        # Poll the actual read-only files; never write or fabricate terminal state.
        while True:
            try:
                for path in (state_path, log_path, owner_path):
                    scoped_path(path)
                state_raw, log_raw, owner_raw = state_path.read_bytes(), log_path.read_bytes(), owner_path.read_bytes()
                require(len(state_raw) <= 4 * 1024 * 1024 and len(owner_raw) <= 4096, "bootstrap_private_record_limit")
                events = complete_bootstrap_log(log_raw)
                with self.model.lock:
                    require(self.model.rejections == 0, "bootstrap_provider_rejected_or_send_failed")
                    issued = {key: value for key, value in self.model.accepted_routing.items() if key not in issued_before}
                if events and any(event.get("type") == "run:done" for event in events) and issued:
                    break
            except FileNotFoundError:
                pass  # actual stock files may not yet exist while appends flush
            require(time.monotonic() < deadline, "bootstrap_terminal_log_not_flushed")
            time.sleep(0.05)
        proof = verify_bootstrap_records(strict_json(state_raw), events, graph=self.graph,
                    conversation=conversation, accepted_routing=issued, reply=reply, provider_rejections=self.model.rejections,
                    owner=strict_json(owner_raw), expected_owner=expected_owner)
        self.bootstrap_receipts[session_id] = {**proof, "state_sha256": hashlib.sha256(state_raw).hexdigest(),
                                               "log_sha256": hashlib.sha256(log_raw).hexdigest(),
                                               "owner_sha256": hashlib.sha256(owner_raw).hexdigest()}

    def _context(self, actor, cookie):
        self._guard()
        from frontend_helpers.frontend_observers import read_login_session
        context = self.latest[actor]
        session = read_login_session(context.observer.paths, cookie=token_from_cookie(cookie),
                    expected_profile=context.scope.profile_id, expected_customer=context.scope.customer_id,
                    snapshot=context.scope.snapshot, source_fingerprint=context.scope.source_fingerprint)
        require(session.session_id in self.contexts and self.contexts[session.session_id].actor == actor,
                "fixture_bound_session_required")
        return self.contexts[session.session_id]

    def arm_response_loss(self, actor, cookie, operation, target):
        context = self._context(actor, cookie)
        require(self.fault is None and context.reference is not None, "fault_already_armed_or_general")
        require((operation == "prepare" and target is None and self.phase == "stock-prepare-response-loss")
                or (operation == "confirm" and isinstance(target, str) and self.phase == "authored-confirm-response-loss"),
                "fault_phase_or_target")
        self.fault = {"operation": operation, "context": context, "target": target}
        async def attach():
            self._attach_fault()
        asyncio.run_coroutine_threadsafe(attach(), self.loop).result(timeout=15)

    def _attach_fault(self):
        if self.fault is None:
            return
        import httpx
        from frontend_helpers.frontend_fault import FileConsumedJournal, PrepareDropTransport
        from frontend_helpers.frontend_confirm_fault import FileConfirmJournal, ConfirmDropTransport, ConfirmScope
        context = self.fault["context"]
        observer = context.observer  # same coordinator, including confirmation baseline on restart
        inner = lambda: httpx.AsyncHTTPTransport(trust_env=False)
        if self.fault["operation"] == "prepare":
            journal = FileConsumedJournal(context.scope, fixture_root=self.root, path=self.root / "prepare-consumed.json")
            wrapper = PrepareDropTransport(context.scope, inner_factory=inner, verify_identity=observer.identity_verifier,
                      resolve_host_intent=observer.resolve_host_intent, verify_commit=observer.verify_commit,
                      record_consumed=journal.record, consumed=journal.load())
        else:
            if "confirm_scope" not in self.fault:
                # Must capture absence/baseline BEFORE any confirm forwarding.
                original = observer.capture_confirmation_base(context.reference, self.fault["target"])
                self.fault["confirm_scope"] = ConfirmScope(context.scope, original, context.reference,
                            hashlib.sha256(self.fault["target"].encode()).hexdigest())
            scope = self.fault["confirm_scope"]
            journal = FileConfirmJournal(scope, fixture_root=self.root, path=self.root / "confirm-consumed.json")
            wrapper = ConfirmDropTransport(scope, inner_factory=inner, verify_identity=observer.identity_verifier,
                      resolve_confirmation_intent=observer.resolve_confirmation_intent,
                      verify_confirmation_commit=observer.verify_confirmation_commit,
                      record_consumed=journal.record, consumed=journal.load())
        self.fault.update(journal=journal, wrapper=wrapper)
        self.app.state.chat_service._transport = wrapper

    def observe(self):
        self._guard()
        counts = transport_counts((self.root / "transport-events.jsonl").read_bytes(), generations=self.generations)
        with read_db(self.ledger.bank) as db:
            self.ledger.generation(db)
            rows = {key: db.execute("SELECT count(*) FROM " + table).fetchone()[0] for key, table in
                    (("cases", "sandbox_cases"), ("receipts", "sandbox_case_receipts"),
                     ("handoffs", "sandbox_handoffs"), ("pending", "action_pending"))}
        require(self.model.rejections == 0, "fixture_provider_rejected_request")
        consumed = self.fault["journal"].load() if self.fault else None
        return {**rows, **counts, "fixture_provider_calls": self.model.calls,
                "forwarded_faults": int(consumed is not None)}

    def read_coverage(self):
        self._guard()
        with read_db(self.ledger.bank) as db:
            generation = self.ledger.generation(db)
            rows = [dict(row) for row in db.execute("SELECT * FROM sandbox_coverage")]
        require(len(rows) <= 1, "coverage_row_inventory")
        if rows:
            row = rows[0]
            require(row["generation"] == generation and row["coverage_start"] == self.metadata["coverage_start"],
                    "coverage_config_binding")
        return {"rows": len(rows), "complete": bool(rows),
                "configured_start_matches": bool(rows) and rows[0]["coverage_start"] == self.metadata["coverage_start"],
                "generation_matches": bool(rows) and rows[0]["generation"] == generation}

    def read_risk_by_request(self, actor, request_id):
        self._guard()
        return strict_json(self.ledger.pending_by_request(self.latest[actor], request_id)["result_json"])["risk"]

    def read_saved_receipt(self, case_id):
        self._guard()
        return self.ledger.receipt(case_id, self.contexts.values())

    def read_saved_handoff(self, handoff_id):
        self._guard()
        return self.ledger.handoff(handoff_id, self.contexts.values())

    def read_saved_handoff_by_request(self, actor, request_id):
        self._guard()
        context = self.latest[actor]
        pending = self.ledger.pending_by_request(context, request_id)
        with read_db(self.ledger.bank) as db:
            row = one(db, "SELECT id FROM sandbox_handoffs WHERE idempotency_key=?", (pending["request_key"],))
        return self.read_saved_handoff(row["id"])

    def read_prepare_recovery(self, actor, cookie):
        context = self._context(actor, cookie)
        require(self.fault and self.fault["operation"] == "prepare" and self.fault["context"] is context,
                "prepare_fault_context")
        marker = self.fault["journal"].load()
        require(marker is not None, "prepare_fault_not_consumed")
        pending = self.ledger.pending_by_request(context, marker.intent.binding.request_id)
        require(pending["id"] == marker.proof.pending_handle_sha256, "prepare_pending_handle_join")
        handoff = self.read_saved_handoff(marker.proof.handoff_id)
        with read_db(self.ledger.bank) as db:
            handoff_row = one(db, "SELECT * FROM sandbox_handoffs WHERE idempotency_key=?", (pending["request_key"],))
        require(canonical(handoff["packet"]) == marker.proof.handoff_packet_sha256
                and canonical(pending) == marker.proof.pending_row_digest
                and handoff_row["id"] == marker.proof.handoff_id
                and canonical(handoff_row) == marker.proof.handoff_row_digest, "prepare_consumed_commit_join")
        with read_db(context.observer.paths.frontend_chat_db) as db:
            action = one(db, "SELECT * FROM action_status WHERE session_id=?", (context.scope.frontend_session_id,))
            session = one(db, "SELECT * FROM chat_sessions WHERE session_id=?", (context.scope.frontend_session_id,))
        current_saved = strict_json(action["result_json"])
        require(action["owner"] == session["owner"] == context.scope.frontend_owner
                and session["subject"] == context.scope.subject and session["customer_id"] == context.scope.customer_id
                and session["expires"] == context.scope.frontend_session_exp and session["revoked"] == 0
                and action["action_id"] == marker.intent.action_id and action["revision"] >= marker.intent.revision
                and action["target_reference"] == context.reference and session["conversation_id"] == context.conversation
                and session["conversation_id"] == marker.intent.binding.conversation_id
                and action["expires"] == context.scope.frontend_session_exp
                and current_saved.get("request_id") == marker.intent.binding.request_id
                and current_saved.get("state") in {"preparing", "prepare_unverified", "handoff_verified"},
                "prepare_current_host_join")
        return {"host_request_id": marker.intent.binding.request_id, "action_id": action["action_id"],
                "revision": action["revision"], "conversation_sha256": hashlib.sha256(context.conversation.encode()).hexdigest(),
                "pending_handle_sha256": marker.proof.pending_handle_sha256, "pending_identity_count": 1,
                "handoff_id": handoff["id"], "handoff_packet_sha256": canonical(handoff["packet"]),
                "ledger_generation": self.metadata["generation"], "target_matches": True,
                "completed_upstream": True, "consumed": True}

    def read_consumed_fault(self, actor, operation, target):
        self._guard()
        require(self.fault and operation == self.fault["operation"] and actor == self.fault["context"].actor
                and target == self.fault["target"], "consumed_fault_target")
        marker = self.fault["journal"].load()
        require(marker is not None, "fault_not_consumed")
        receipt, handoff_id = None, None
        if operation == "confirm":
            receipt = self.read_saved_receipt(marker.proof.case_id)
            context = self.fault["context"]
            observed = context.observer.verify_fresh_confirmation(self.fault["confirm_scope"].original_intent,
                                                                  target, context.reference, receipt)
            require(canonical(receipt) == marker.proof.receipt_sha256
                    and all(observed[field] == getattr(marker.proof, field) for field in
                            ("case_id", "pending_row_digest", "case_row_digest", "receipt_row_digest", "receipt_sha256")),
                    "confirm_consumed_receipt_join")
        else:
            handoff_id = self.read_saved_handoff(marker.proof.handoff_id)["id"]
        return {"operation": operation, "target_matches": True, "completed_upstream": True, "consumed": True,
                "consent": operation == "confirm", "receipt": receipt, "handoff_id": handoff_id}

    def _stop_frontend(self):
        if self.front_server is not None:
            self.front_server.should_exit = True
            self.front_thread.join(timeout=15)
            require(not self.front_thread.is_alive(), "frontend_stop_timeout")
            self.front_server = self.front_thread = None

    def _stop_worker(self):
        if self.worker is not None:
            if self.worker.poll() is None:
                os.killpg(self.worker.pid, signal.SIGTERM)
                try:
                    self.worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(self.worker.pid, signal.SIGKILL)
                    self.worker.wait(timeout=5)
            self.worker = None

    def restart_preserving_state(self):
        self._guard()
        before = self.observe()
        self._stop_frontend()
        self._stop_worker()
        # Same workspace/restore archive, policy/keys/demo code/config binding,
        # front databases, bank database/generation, generated snapshot, model
        # provider, coordinator/baselines and consumed journals. No regeneration.
        self._start_worker()
        self._start_frontend()
        after = self.observe()
        require(all(after[key] == before[key] for key in ("cases", "receipts", "handoffs", "pending", "tool_calls",
                                                        "forwarded_faults", "fixture_provider_calls")), "restart_changed_evidence")

    def stop(self):
        try:
            self._stop_frontend()
        finally:
            try:
                self._stop_worker()
            finally:
                if self.model is not None:
                    self.model.stop()
                    self.model = None
