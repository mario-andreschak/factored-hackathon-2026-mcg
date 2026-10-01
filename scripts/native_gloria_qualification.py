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
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone


PIN = "0ba62296520a505e6d71eddf5aa650691f3dc311"
ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {"package.json", "package-lock.json", "next.config.mjs", "next-env.d.ts", "tsconfig.json",
              "tsconfig.build.json", "postcss.config.mjs", "eslint.config.mjs", "LICENSE"}
PREFIXES = ("src/", "scripts/", "mcp-servers/", "public/", "bin/")


class NativeGloriaPort:
    """ChatService-compatible host workflow port using restricted native stages.

    ``workflow_factory(model)`` must construct the owner's application Workflow.
    The returned state is the application's validated response; no FLUJO relay
    is rendered. The admission directory belongs only to the isolated service.
    """
    def __init__(self, workflow_factory, base_url, authority_dir, *, timeout=90):
        self.workflow_factory = workflow_factory
        self.base_url, self.authority_dir, self.timeout = base_url, Path(authority_dir), timeout

    @contextmanager
    def _edit_admissions(self):
        location = self.authority_dir / "admissions.json"
        lock = self.authority_dir / ".admissions-host.lock"
        self.authority_dir.mkdir(parents=True, exist_ok=True)
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
                    json.dump(records, output, ensure_ascii=False)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, location)
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
        from gloria_workflow.model import FlujoModel
        from gloria_workflow.state import TrustedBinding, parse_timestamp, utc_now
        trusted = binding if isinstance(binding, TrustedBinding) else TrustedBinding(**binding)
        if not trusted.authenticated or trusted.expired(utc_now()):
            raise ValueError("native admitted identity unavailable")
        if not isinstance(message, str) or not message or len(message) > 4096 or not isinstance(turn_id, str):
            raise ValueError("native admitted turn required")
        expiry = min(time.time() * 1000 + 600000, parse_timestamp(trusted.expires_at).timestamp() * 1000)
        record = {"mode": "language_only", "token": secrets.token_hex(24), "stageToken": secrets.token_hex(24),
                  "owner": trusted.owner, "conversation": trusted.conversation_id,
                  "runId": str(uuid.uuid4()), "turnId": turn_id, "message": message,
                  "graphHash": "", "flowId": "", "server": "gloria-language-only", "expires": expiry}
        record["bindingFingerprint"] = digest(json.dumps([trusted.owner, trusted.customer_id, trusted.session_id,
            trusted.conversation_id, parse_timestamp(trusted.expires_at).timestamp()], separators=(",", ":")).encode())
        with self._edit_admissions() as records:
            records.append(record)
        try:
            model = FlujoModel(self.base_url, "model-gloria-native-model", record["stageToken"], timeout=self.timeout)
            workflow = self.workflow_factory(model)
            result = await workflow.run(deepcopy(binding), message, turn_id=turn_id, selection=deepcopy(selection), **kwargs)
            return result
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
    paths = [ROOT / "scripts/native_gloria_qualification.ts", ROOT / "scripts/native_gloria_qualification.py",
             ROOT / "scripts/native_gloria_qualification.mjs", ROOT / "scripts/native_gloria_qualification.Dockerfile",
             ROOT / "scripts/build_gloria_graph.mjs", ROOT / "graph_config_v3.yaml",
             ROOT / "scripts/native_gloria_compatibility_probe.mjs",
             ROOT / "scripts/native_gloria_capability_probe.mjs", ROOT / "scripts/native_gloria_bridge_loader.mjs",
             ROOT / "scripts/qualify_gloria.py", ROOT / "requirements-gloria.txt", ROOT / "requirements-pipeline.txt",
             ROOT / "requirements-s3.txt", ROOT / "frontend/requirements.txt"]
    for directory, suffix in (("gloria_workflow", "*.py"), ("resources/prompts", "*.yml"),
                              ("resources/policies", "*.md"), ("config", "*.yaml"),
                              ("contracts", "*.md"), ("banking_mcp", "*.py"), ("frontend/server", "*.py")):
        paths.extend((ROOT / directory).glob(suffix))
    paths.append(ROOT / "resources/prompts/fallback_templates.yaml")
    for source in paths:
        relative = source.relative_to(ROOT)
        destination = qualification / (relative.name if relative.parts[0] == "scripts" else relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        destination.write_bytes(data)
        copied[relative.as_posix()] = digest(data)
    shutil.copyfile(ROOT / "scripts/native_gloria_qualification.Dockerfile", context / "Dockerfile")
    catalog_data = catalog.read_bytes()
    models = json.loads(catalog_data)
    for model in models["models"]:
        if model["slug"] in {"gpt-6-sol", "gpt-6-luna"} and (model.get("apply_patch_tool_type") is not None
            or model.get("experimental_supported_tools") or not model.get("node_repl_disabled")):
            raise ValueError("catalog has native capabilities")
    (context / "catalog.json").write_bytes(catalog_data)
    report = {"schema": "gloria-native-source-context/v1", "flujo_revision": PIN,
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
    from gloria_workflow.model import FlujoModel
    from gloria_workflow.prompts import StageAdapters
    from gloria_workflow.runtime import Workflow
    from gloria_workflow.state import ConversationStore
    from gloria_workflow.tool import create_mcp_server
    from qualify_gloria import SyntheticBank
    record = json.loads(admission.read_text(encoding="utf-8"))
    if record["expires"] <= datetime.now(timezone.utc).timestamp() * 1000:
        raise ValueError("expired admission")
    binding = record["binding"]
    model = FlujoModel("http://127.0.0.1:4200", "model-gloria-native-model", record["stageToken"], timeout=90)
    timeout = 0.01 if record.get("scenario") == "timeout" else 90
    state_path = admission.parent.parent / "workflow-state.sqlite3"
    bank = SyntheticBank(datetime.now(timezone.utc))
    class ObservedModel:
        async def __call__(self, stage, system, user):
            raw = await model(stage, system, user)
            # Synthetic diagnostics only. Joined host uses NativeGloriaPort,
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
        if name == "scripts/native_gloria_qualification.ts":
            source = Path("/app/gloria-qualification-adapter.ts")
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
    args = parser.parse_args()
    if args.verify_image:
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
