"""Prepare an exact public source image context or serve one admitted synthetic turn.

No shared worker configuration, bank records or credentials enter build contexts.
The runtime host supplies an independent private admission file and login mount.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import os
import secrets
import stat
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone


PIN = "0ba62296520a505e6d71eddf5aa650691f3dc311"
ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {"package.json", "package-lock.json", "next.config.mjs", "next-env.d.ts", "tsconfig.json",
              "tsconfig.build.json", "postcss.config.mjs", "eslint.config.mjs", "LICENSE"}
PREFIXES = ("src/", "scripts/", "mcp-servers/", "public/", "bin/")


class NativeDisputePort:
    """ChatService-compatible host workflow port using restricted native stages.

    ``workflow_factory(model)`` must construct the owner's application Workflow.
    The returned state is the application's validated response; no FLUJO relay
    is rendered. The admission directory belongs only to the isolated service.
    """
    def __init__(self, workflow_factory, base_url, authority_dir, *, timeout=90, reader_group=None):
        if reader_group is not None and (os.name != "posix" or type(reader_group) is not int
                                         or reader_group < 1):
            raise ValueError("native reader group requires a POSIX group id")
        self.workflow_factory = workflow_factory
        self.base_url, self.authority_dir, self.timeout = base_url, Path(authority_dir), timeout
        self.reader_group = reader_group
        if reader_group is not None:
            if reader_group not in {os.getegid(), *os.getgroups()}:
                raise ValueError("native reader group is not available to writer")
            self._check_control(self.authority_dir, 0o2750, directory=True)
            self._check_control(self.authority_dir / "admissions.json", 0o640)
            lock = self.authority_dir / ".admissions-host.lock"
            if lock.exists() or lock.is_symlink():
                info = lock.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                        or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                    raise ValueError("native host lock permissions mismatch")
            revocations = self.authority_dir / "revocations"
            if revocations.exists() or revocations.is_symlink():
                self._check_control(revocations, 0o2750, directory=True)
                for marker in revocations.iterdir():
                    self._check_control(marker, 0o640)

    def _check_control(self, path, mode, *, directory=False):
        if self.reader_group is None:
            return
        info = path.lstat()
        if (info.st_uid != os.geteuid() or info.st_gid != self.reader_group
                or stat.S_IMODE(info.st_mode) != mode
                or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
                or not directory and info.st_nlink != 1):
            raise ValueError("native control permissions mismatch")

    def _publish_mode(self, descriptor, mode):
        if self.reader_group is not None:
            os.fchown(descriptor, -1, self.reader_group)
            os.fchmod(descriptor, mode)
            info = os.fstat(descriptor)
            if info.st_gid != self.reader_group or stat.S_IMODE(info.st_mode) != mode:
                raise ValueError("native control group publication failed")

    def _revocations_dir(self):
        directory = self.authority_dir / "revocations"
        if self.reader_group is None:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        else:
            self._check_control(self.authority_dir, 0o2750, directory=True)
            if not directory.exists():
                directory.mkdir(mode=0o700)
                os.chown(directory, -1, self.reader_group)
                os.chmod(directory, 0o2750)
            self._check_control(directory, 0o2750, directory=True)
        return directory

    def _revoke_stage(self, stage_token):
        # A registry reader may prevent replacement on Windows. Publish an
        # independent monotonic denial before attempting registry cleanup.
        directory = self._revocations_dir()
        location = directory / (digest(stage_token.encode()) + ".revoked")
        if self.reader_group is None:
            try:
                descriptor = os.open(location, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                # Presence is a monotonic denial.
                pass
            else:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(b"revoked\n")
                    output.flush()
                    os.fsync(output.fileno())
        else:
            # A complete group-readable tombstone becomes visible at its final
            # name in one hard-link publication. Never expose a 0600 half-write
            # at that name to the worker reader.
            temporary = directory / (".revoked-" + uuid.uuid4().hex + ".tmp")
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    self._publish_mode(output.fileno(), 0o640)
                    output.write(b"revoked\n")
                    output.flush()
                    os.fsync(output.fileno())
                try:
                    os.link(temporary, location)
                except FileExistsError:
                    pass
            finally:
                temporary.unlink(missing_ok=True)
            self._check_control(location, 0o640)
        if os.name == "posix":
            for parent in (directory, self.authority_dir):
                directory_descriptor = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory_descriptor)
                finally:
                    os.close(directory_descriptor)

    @contextmanager
    def _edit_admissions(self):
        location = self.authority_dir / "admissions.json"
        lock = self.authority_dir / ".admissions-host.lock"
        self.authority_dir.mkdir(parents=True, exist_ok=True)
        self._check_control(self.authority_dir, 0o2750, directory=True)
        self._check_control(location, 0o640)
        # Keep one stable inode. The kernel releases its lock after a crash;
        # existence of an old marker never grants or blocks admission.
        descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
        if os.name == "nt":
            import msvcrt
            def acquire():
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            def release():
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        deadline, acquired = time.monotonic() + 5, False
        try:
            while not acquired:
                try:
                    acquire(); acquired = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ValueError("native admission writer unavailable") from None
                    time.sleep(0.01)
            records = json.loads(location.read_text(encoding="utf-8")) if location.exists() else []
            yield records
            temporary = location.with_name("admissions-" + uuid.uuid4().hex + ".json")
            temporary_descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                with os.fdopen(temporary_descriptor, "w", encoding="utf-8") as output:
                    self._publish_mode(output.fileno(), 0o640)
                    json.dump(records, output, ensure_ascii=False)
                    output.flush()
                    os.fsync(output.fileno())
                # Docker bind-mount readers can briefly deny delete sharing on
                # Windows. Keep the writer lock and the same fsynced file until
                # atomic replacement succeeds; never truncate the live registry.
                replacement_deadline = time.monotonic() + 5
                while True:
                    try:
                        os.replace(temporary, location)
                        self._check_control(location, 0o640)
                        break
                    except PermissionError as error:
                        if (os.name != "nt" or getattr(error, "winerror", None) not in {5, 32, 33}
                                or time.monotonic() >= replacement_deadline):
                            raise
                        time.sleep(0.01)
                if os.name == "posix":
                    directory_descriptor = os.open(self.authority_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                    try:
                        os.fsync(directory_descriptor)
                    finally:
                        os.close(directory_descriptor)
            finally:
                temporary.unlink(missing_ok=True)
        finally:
            if acquired:
                release()
            os.close(descriptor)

    async def run(self, binding, message, *, turn_id, selection=None, **kwargs):
        from copy import deepcopy
        from dispute_workflow.model import FlujoModel
        from dispute_workflow.state import TrustedBinding, parse_timestamp, utc_now
        trusted = binding if isinstance(binding, TrustedBinding) else TrustedBinding(**binding)
        if not trusted.authenticated or trusted.expired(utc_now()):
            raise ValueError("native admitted identity unavailable")
        if not isinstance(message, str) or not message or len(message) > 4096 or not isinstance(turn_id, str):
            raise ValueError("native admitted turn required")
        expiry = min(time.time() * 1000 + 600000, parse_timestamp(trusted.expires_at).timestamp() * 1000)
        self._revocations_dir()
        record = {"mode": "language_only", "token": secrets.token_hex(24), "stageToken": secrets.token_hex(24),
                  "owner": trusted.owner, "conversation": trusted.conversation_id,
                  "runId": str(uuid.uuid4()), "turnId": turn_id, "message": message,
                  "graphHash": "", "flowId": "", "server": "dispute-language-only", "expires": expiry}
        record["bindingFingerprint"] = digest(json.dumps([trusted.owner, trusted.customer_id, trusted.session_id,
            trusted.conversation_id, parse_timestamp(trusted.expires_at).timestamp()], separators=(",", ":")).encode())
        with self._edit_admissions() as records:
            records.append(record)
        try:
            model = FlujoModel(self.base_url, "model-dispute-native-model", record["stageToken"], timeout=self.timeout)
            workflow = self.workflow_factory(model)
            result = await workflow.run(deepcopy(binding), message, turn_id=turn_id, selection=deepcopy(selection), **kwargs)
            return result
        finally:
            try:
                self._revoke_stage(record["stageToken"])
            finally:
                with self._edit_admissions() as records:
                    records[:] = [item for item in records if item.get("stageToken") != record["stageToken"]]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare(flujo_root: Path, context: Path, catalog: Path, native_binary=None, native_version=None):
    revision = subprocess.check_output(["git", "-C", str(flujo_root), "rev-parse", "HEAD"], text=True).strip()
    if revision != PIN or context.exists():
        raise ValueError("new context and exact permitted source checkout required")
    archive = subprocess.check_output(["git", "-C", str(flujo_root), "archive", "--format=tar", PIN])
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
        for member in source:
            name = member.name
            if name not in ROOT_FILES and not name.startswith(PREFIXES):
                continue
            relative = PurePosixPath(name)
            if not member.isfile() or relative.is_absolute() or ".." in relative.parts:
                if member.isdir():
                    continue
                raise ValueError("unreviewed context source")
            if any(part in {".git", "node_modules", ".next", "private", "data"} or part.startswith(".env") for part in relative.parts):
                raise ValueError("private context source")
            data = source.extractfile(member).read()
            output = context / "flujo" / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
            files[name] = digest(data)
    qualification = context / "qualification"
    copied = {}
    paths = [ROOT / ".gitattributes", ROOT / "pipeline/contracts.yaml",
             ROOT / "scripts/native_dispute_qualification.ts", ROOT / "scripts/native_dispute_qualification.py",
             ROOT / "scripts/native_dispute_qualification.mjs", ROOT / "scripts/native_dispute_qualification.Dockerfile",
             ROOT / "scripts/build_dispute_graph.mjs", ROOT / "graph_config_v3.yaml",
             ROOT / "resources/dispute_workflow.flow.json",
             ROOT / "scripts/native_dispute_compatibility_probe.mjs",
             ROOT / "scripts/native_dispute_capability_probe.mjs", ROOT / "scripts/native_dispute_bridge_loader.mjs",
             ROOT / "scripts/native_dispute_revocation_probe.mjs",
             ROOT / "scripts/qualify_dispute.py", ROOT / "requirements-dispute.txt", ROOT / "requirements-mcp.txt", ROOT / "requirements-pipeline.txt",
             ROOT / "requirements-s3.txt", ROOT / "frontend/requirements.txt"]
    for directory, suffix in (("dispute_workflow", "*.py"), ("resources/prompts", "*.yml"),
                              ("resources/policies", "*.md"), ("config", "*.yaml"),
                              ("contracts", "*.md"), ("banking_mcp", "*.py"), ("frontend/server", "*.py"),
                              ("pipeline", "*.py")):
        paths.extend((ROOT / directory).glob(suffix))
    paths.append(ROOT / "resources/prompts/fallback_templates.yaml")
    for source in paths:
        if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError("Public application source must be an owned regular file")
        relative = source.relative_to(ROOT)
        destination = qualification / (relative.name if relative.parts[0] == "scripts" else relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        destination.write_bytes(data)
        copied[relative.as_posix()] = digest(data)
    shutil.copyfile(ROOT / "scripts/native_dispute_qualification.Dockerfile", context / "Dockerfile")
    catalog_data = catalog.read_bytes()
    models = json.loads(catalog_data)
    for model in models["models"]:
        if model["slug"] in {"gpt-6-sol", "gpt-6-luna"} and (model.get("apply_patch_tool_type") is not None
            or model.get("experimental_supported_tools") or not model.get("node_repl_disabled")):
            raise ValueError("catalog has native capabilities")
    (context / "catalog.json").write_bytes(catalog_data)
    report = {"schema": "dispute-native-source-context/v1", "flujo_revision": PIN,
              "application_revision": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
              "flujo_files": files, "application_files": copied, "catalog_sha256": digest(catalog_data),
              "credential_files": 0, "runtime_installed": False}
    if native_binary is not None:
        if native_version not in {"0.153.3", "0.157.1"} or not native_binary.is_file() or native_binary.is_symlink():
            raise ValueError("verified dedicated native binary required")
        binary_bytes = native_binary.read_bytes()
        binary_output = qualification / "bin/codex"
        binary_output.parent.mkdir()
        binary_output.write_bytes(binary_bytes)
        report["native_binary"] = {"version": native_version, "sha256": digest(binary_bytes), "installed_path": "/qualification/bin/codex"}
    else:
        raise ValueError("Dedicated verified Linux native binary required for reproducible image")
    (context / "source-manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return {"flujo_revision": PIN, "source_files": len(files), "application_files": len(copied),
            "catalog_sha256": report["catalog_sha256"], "credential_files": 0}


def serve(admission: Path):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dispute_workflow.model import FlujoModel
    from dispute_workflow.prompts import StageAdapters
    from dispute_workflow.runtime import Workflow
    from dispute_workflow.state import ConversationStore
    from dispute_workflow.tool import create_mcp_server
    from qualify_dispute import SyntheticBank
    record = json.loads(admission.read_text(encoding="utf-8"))
    if record["expires"] <= datetime.now(timezone.utc).timestamp() * 1000:
        raise ValueError("expired admission")
    binding = record["binding"]
    model = FlujoModel("http://127.0.0.1:4200", "model-dispute-native-model", record["stageToken"], timeout=90)
    timeout = 0.01 if record.get("scenario") == "timeout" else 90
    state_path = admission.parent.parent / "workflow-state.sqlite3"
    bank = SyntheticBank(datetime.now(timezone.utc))
    class ObservedModel:
        async def __call__(self, stage, system, user):
            raw = await model(stage, system, user)
            # Synthetic diagnostics only. Joined host uses NativeDisputePort,
            # which never writes customer prompt/result bodies to this trace.
            trace = admission.parent.parent / "observed" / (record["turnId"] + "-synthetic-stages.jsonl")
            trace.parent.mkdir(exist_ok=True)
            with trace.open("a", encoding="utf-8") as output:
                output.write(json.dumps({"stage": stage, "user": user, "raw": raw}, ensure_ascii=False) + "\n")
            return raw
    workflow = Workflow(StageAdapters(ObservedModel(), timeout_seconds=timeout), bank, ConversationStore(state_path))
    class ObservedWorkflow:
        async def run(self, *args, **kwargs):
            result = await workflow.run(*args, **kwargs)
            observed = {"model_observations": model.observations, "bank_calls": bank.calls,
                        "safe_fallback_used": result.get("runtime", {}).get("safe_fallback_used", False),
                        "stage_errors": result.get("runtime", {}).get("node_errors", []),
                        "attack": result.get("turn", {}).get("attack"),
                        "response_mode": result.get("workflow_state", {}).get("policy_decision", {}).get("response_mode")}
            output = admission.parent.parent / "observed" / (record["turnId"] + ".json")
            output.parent.mkdir(exist_ok=True)
            output.write_text(json.dumps(observed, ensure_ascii=False), encoding="utf-8")
            return result
    server = create_mcp_server(ObservedWorkflow(), binding, record["message"], record["turnId"], selection=record.get("selection"), query_scope_id=record.get("query_scope_id"))
    server.run(transport="stdio")


def verify_image(manifest: Path):
    """Hash actual installed source bytes without reading runtime secrets."""
    expected = json.loads(manifest.read_text(encoding="utf-8"))
    failures = []
    for name, checksum in expected["flujo_files"].items():
        source = Path("/app") / name
        if not source.is_file() or digest(source.read_bytes()) != checksum:
            failures.append("flujo:" + name)
    for name, checksum in expected["application_files"].items():
        relative = PurePosixPath(name)
        if name == "scripts/native_dispute_qualification.ts":
            source = Path("/app/dispute-qualification-adapter.ts")
        elif relative.parts[0] == "scripts":
            source = Path("/qualification") / relative.name
        elif name.startswith("requirements-") or name == "frontend/requirements.txt":
            source = Path("/tmp") / relative
        else:
            source = Path("/qualification") / relative
        if not source.is_file() or digest(source.read_bytes()) != checksum:
            failures.append("application:" + name)
    binary = expected.get("native_binary")
    if binary and digest(Path(binary["installed_path"]).read_bytes()) != binary["sha256"]:
        failures.append("native:binary")
    return {"pass": not failures, "flujo_files": len(expected["flujo_files"]),
            "application_files": len(expected["application_files"]), "failures": failures,
            "manifest_sha256": digest(manifest.read_bytes())}


BOUNDARY_CASES = {
    "normal_es", "normal_es_transport_replay", "restart_transport_replay",
    "restart_foreign_conversation", "restart_foreign_session_same_owner",
    "normal_pt", "normal_pt_transport_replay", "timeout", "timeout_transport_replay",
    "slow_body_concurrent_replay", "concurrent_replay", "concurrent_replay_transport_replay",
    "poison_state", "poison_state_transport_replay",
}
CAPABILITY_CASES = {(model, tool) for model in ("gpt-6-sol", "gpt-6-luna")
                    for tool in ("inventory", "approved_mcp", "read_mcp_resource", "rogue_namespace",
                                 "mcp__rogue__rogue_access", "apply_patch_foreign", "functions_exec")}
REVOCATION_CASES = {"initial_stage_revocation", "revocation_during_body_await", "foreign_marker_preserves_sibling",
                    "cancelled_cleanup_late_callback"}
REVOCATION_FENCE_CASES = {"initial_revocation_blocks_registry_read", "revocation_after_registry_await",
                        "foreign_marker_preserves_sibling", "unexpected_marker_io_denied",
                        "unavailable_authority_directory_denied"}


async def probe_cancel_cleanup(base_url, authority_dir):
    """Zero-provider installed callback probe with a real Windows sharing denial."""
    import asyncio
    import ctypes
    from ctypes import wintypes
    import httpx
    if os.name != "nt":
        raise ValueError("Real Windows delete-sharing qualification required")
    directory = Path(authority_dir)
    location, events = directory / "admissions.json", directory / "events.jsonl"
    before = events.read_bytes() if events.exists() else b""
    sibling_tokens = {item.get("stageToken") for item in json.loads(location.read_text(encoding="utf-8"))}
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle, own, model = None, None, None
    turn = str(uuid.uuid4())
    class Workflow:
        async def run(self, *_args, **_kwargs):
            nonlocal handle, own
            own = next(item for item in json.loads(location.read_text(encoding="utf-8")) if item.get("turnId") == turn)
            handle = kernel.CreateFileW(str(location), 0x80000000, 1, None, 3, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                raise OSError("Windows sharing fixture unavailable")
            raise asyncio.CancelledError()
    def factory(admitted_model):
        nonlocal model
        model = admitted_model
        return Workflow()
    port = NativeDisputePort(factory, base_url, directory)
    cleanup_failed = False
    began = time.monotonic()
    try:
        try:
            await port.run({"owner": "synthetic-cancel-owner", "customer_id": "public-synthetic",
                "session_id": str(uuid.uuid4()), "conversation_id": str(uuid.uuid4()),
                "expires_at": time.time() + 60}, "Original synthetic callback", turn_id=turn)
        except PermissionError:
            cleanup_failed = True
    finally:
        if handle is not None and handle != ctypes.c_void_p(-1).value:
            kernel.CloseHandle(handle)
    if own is None or model is None:
        raise ValueError("Cancellation fixture did not admit a turn")
    retained = json.loads(location.read_text(encoding="utf-8"))
    marker_exists = (directory / "revocations" / (digest(own["stageToken"].encode()) + ".revoked")).is_file()
    async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
        late = await client.post(base_url + "/v1/chat/completions",
            headers={"Authorization": "Bearer " + model._token},
            json={"model": "model-dispute-native-model", "messages": [{"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": "Original synthetic callback"}], "stream": False})
    revoked_denial = late.status_code == 403 and late.json().get("error") == "dispute_stage_revoked"
    unchanged = before == (events.read_bytes() if events.exists() else b"")
    siblings_preserved = sibling_tokens <= {item.get("stageToken") for item in retained}
    stale_record = any(item.get("stageToken") == own["stageToken"] and item["expires"] > time.time() * 1000 for item in retained)
    with port._edit_admissions() as records:
        records[:] = [item for item in records if item.get("stageToken") != own["stageToken"]]
    return {"case": "cancelled_cleanup_late_callback", "pass": cleanup_failed and marker_exists and stale_record
            and siblings_preserved and revoked_denial and unchanged,
            "httpStatus": late.status_code, "seconds": round(time.monotonic() - began, 3),
            "registryCleanupDenied": cleanup_failed, "revocationMarkerPresent": marker_exists,
            "staleOwnRecordDenied": stale_record and revoked_denial,
            "siblingsPreserved": siblings_preserved, "noProviderOrMcpBeforeDenial": unchanged,
            "sharingFixture": "actual Windows reader without delete sharing"}


def public_report(report):
    """Publish an allowlisted successful attestation, never private payloads."""
    cases, probes = report.get("cases", []), report.get("nativeCapabilityProbes", {}).get("cases", [])
    installed, source = report.get("installedSourceHashes", {}), report.get("sourceContext", {})
    audit, native = report.get("imageCredentialAudit", {}), report.get("nativeProfile", {})
    revocations = report.get("revocationProbes", {}).get("cases", [])
    fences = report.get("revocationFenceProbes", {}).get("cases", [])
    if (report.get("pass") is not True or report.get("installed") is not True
            or len(cases) != 14 or {item.get("case") for item in cases} != BOUNDARY_CASES
            or not all(item.get("pass") is True for item in cases)
            or len(probes) != 14 or {(item.get("model"), item.get("tool")) for item in probes} != CAPABILITY_CASES
            or not all(item.get("passed") is True for item in probes)
            or len(revocations) != len(REVOCATION_CASES) or {item.get("case") for item in revocations} != REVOCATION_CASES
            or not all(item.get("pass") is True and item.get("noProviderOrMcpBeforeDenial") is True for item in revocations)
            or len(fences) != len(REVOCATION_FENCE_CASES) or {item.get("case") for item in fences} != REVOCATION_FENCE_CASES
            or not all(item.get("pass") is True and item.get("provider_calls") == 0 for item in fences)
            or report.get("revocationFenceProbes", {}).get("adapterSourceSha256") != source.get("application_files", {}).get("scripts/native_dispute_qualification.ts")
            or report.get("revocationFenceProbes", {}).get("fixtureSha256") != source.get("application_files", {}).get("scripts/native_dispute_revocation_probe.mjs")
            or installed.get("pass") is not True or audit.get("credential_files_present") != 0
            or not report.get("externalManifestSha256")
            or installed.get("manifest_sha256") != report["externalManifestSha256"]
            or installed.get("application_files") != len(source.get("application_files", {}))
            or installed.get("flujo_files") != len(source.get("flujo_files", {}))):
        raise ValueError("Only complete, source-matched installed qualification can be published")
    boundary = []
    for item in cases:
        selected = {key: item[key] for key in ("case", "httpStatus", "seconds", "pass", "graphHash",
                    "exactValidatedProjectionCaptured", "language", "rule_ids", "safe_fallback_used",
                    "noProviderOrMcpBeforeDenial") if key in item}
        if "bank_calls" in item:
            selected["bank_read_count"] = len(item["bank_calls"])
        if "model_observations" in item:
            selected["stage_outcomes"] = [{key: observation[key] for key in ("stage", "status", "latency_ms")
                                            if key in observation} for observation in item["model_observations"]]
        boundary.append(selected)
    return {
        "schema": "dispute-native-release-qualification/v1",
        "qualified_utc": datetime.now(timezone.utc).isoformat(),
        "pass": True, "installed": True,
        "scope": "Isolated local worker; public synthetic development bank fixture; bridge exposes no banking actions",
        "shared_workers_changed": False, "model_relay_authoritative": False,
        "pins": {"flujo_revision": report["flujoRevision"],
                 "application_revision": source["application_revision"],
                 "image_sha256": report["imageIdentity"],
                 "source_manifest_sha256": report["externalManifestSha256"],
                 "package_lock_sha256": source["flujo_files"]["package-lock.json"],
                 "native_version": native["verifiedCliVersion"],
                 "native_binary_sha256": native["verifiedCliSha256"],
                 "catalog_sha256": native["verifiedModelCatalogSha256"],
                 "application_source_hashes": source["application_files"]},
        "installed_source_equality": {"pass": True, "manifest_equals_external_context": True,
                                      "flujo_files": installed["flujo_files"],
                                      "application_files": installed["application_files"]},
        "credential_file_audit": {"image_files_checked": audit["checked"],
                                  "credential_files_present": 0, "credential_material_published": False},
        "configured_model": {key: report["installedModel"][key]
                             for key in ("id", "name", "provider", "adapter", "reasoningEffort")},
        "native_capability_probes": {
            "scope": "Installed native binary and production tool bridge; synthetic upstream responses",
            "bridge_source_sha256": report["nativeCapabilityProbes"]["bridgeSourceSha256"],
            "fixture_sha256": report["nativeCapabilityProbes"]["fixtureSha256"],
            "count": 14,
            "cases": [{key: item[key] for key in ("model", "tool", "passed", "bridgeSafe",
                       "markerExists", "foreignChanged", "foreignLeaked", "rogueCalled") if key in item}
                      for item in probes]},
        "boundary_cases": {"scope": "Actual configured provider, saved graphs and per-turn registered MCP",
                           "count": 14, "cases": boundary},
        "revocation_probes": {"scope": "Installed no-provider stage denial and real Windows cancellation cleanup sharing",
                              "count": len(revocations), "cases": [{key: item[key] for key in ("case", "pass", "httpStatus",
                                  "seconds", "noProviderOrMcpBeforeDenial", "registryCleanupDenied", "revocationMarkerPresent",
                                  "staleOwnRecordDenied", "siblingsPreserved", "sharingFixture") if key in item} for item in revocations]},
        "revocation_fence_probes": {"scope": "Exact installed adapter declarations, deferred registry read, zero provider execution",
                                   "adapter_source_sha256": report["revocationFenceProbes"]["adapterSourceSha256"],
                                   "fixture_sha256": report["revocationFenceProbes"]["fixtureSha256"],
                                   "count": len(fences), "cases": [{key: item[key] for key in ("case", "pass", "provider_calls")} for item in fences]},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdio", action="store_true")
    parser.add_argument("--admission", type=Path)
    parser.add_argument("--flujo-root", type=Path)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--verify-image", type=Path)
    parser.add_argument("--native-binary", type=Path)
    parser.add_argument("--native-version")
    parser.add_argument("--publish-report", type=Path)
    parser.add_argument("--public-output", type=Path)
    parser.add_argument("--probe-cancel-cleanup", action="store_true")
    parser.add_argument("--base-url")
    parser.add_argument("--authority-dir", type=Path)
    args = parser.parse_args()
    if args.probe_cancel_cleanup:
        if not args.base_url or not args.authority_dir:
            parser.error("base-url and authority-dir required")
        import asyncio
        print(json.dumps(asyncio.run(probe_cancel_cleanup(args.base_url, args.authority_dir))))
    elif args.publish_report:
        if not args.public_output:
            parser.error("public-output required")
        public = public_report(json.loads(args.publish_report.read_text(encoding="utf-8")))
        args.public_output.parent.mkdir(parents=True, exist_ok=True)
        args.public_output.write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"published": True, "boundary_cases": 14, "capability_probes": 14}))
    elif args.verify_image:
        report = verify_image(args.verify_image)
        print(json.dumps(report))
        raise SystemExit(0 if report["pass"] else 1)
    elif args.stdio:
        if not args.admission:
            parser.error("admission required")
        serve(args.admission)
    else:
        if not args.flujo_root or not args.context or not args.catalog:
            parser.error("flujo-root, context and catalog required")
        print(json.dumps(prepare(args.flujo_root.resolve(), args.context.resolve(), args.catalog.resolve(), args.native_binary, args.native_version)))


if __name__ == "__main__":
    main()
