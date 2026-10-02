"""Own the existing local frontend; default is a read-only release plan.

This controller never prepares DATA, a ledger, coverage, admissions or retirement.
--spec and --spec-sha256 identify a private, independently reviewed release spec.
Required spec fields (paths are absolute, hashes are lowercase SHA256):

  schema: savia-local-native-controller/v1
  companionRevision, applicationRevision
  image: {reference: immutable registry digest, id: local sha256 image ID}
  compose: {project: hackathon-banking, workingDirectory,
            files: [{path, sha256}], baselineContainerId, baselineImageId, flujoNetwork}
  data: {root, inventory: {path, sha256}}
  nativeVolume: {name, ownerLabelKey, ownerLabelValue}
  evidence: {approvalTemplate, buildReceipt, transitionReceipt, kernel,
             preparation, retirement}  # each is {path, sha256}
  bindingPublisher: {path, sha256}       # reviewed publisher SOURCE, not credentials
  controlDirectory                      # existing private host directory

Preparation is an original-owner receipt, schema savia-local-native-preparation/v1,
binding image/source/native volume/template/transition hashes and the actual
installed read-only verifier result. It also records exact retired frontend ID.
Retirement is schema savia-local-bank-authority-retirement/v1, binding the retained
transition authority proof SHA and each allowed retained RW consumer's full ID
and image ID. It requires dockerDaemonId and guardObserver {path,sha256}, a
separately reviewed read-only observer of the actual authority-disabled/no-respawn
mechanism. Missing observer/source/evidence refuses startup; this controller
does not generate the guard or its proof. Each retiredRwConsumers entry requires
guardMechanismSha256. Unknown canonical-volume RW consumers refuse launch.

After preflight, --run emits a fresh owner32/PID/binding request and holds the
shared lease for at most 60 seconds awaiting the original owner's mechanical
publisher. The publisher writes binding.json in the emitted private directory:
schema savia-local-native-owner-binding/v1; owner_token, controller_pid, head,
image, native_volume, preparation_sha256, publisher_sha256, approval_sha256,
and inspection {method: actual-linux-readback, path, uid:0,gid:0,mode:384,
sha256,volume}. Its SHA must equal the exact canonical approval bytes derived
from the reviewed template plus runtimeLease. This is no new human approval.

Only then may Compose replace the already-retired frontend service. A separate
heartbeat remains live during every blocking call. Stop/restart requests use the
fresh emitted signal paths and exact owner tuple; no name-based cleanup occurs.
Forced death leaves the shared lock for inspection. An uncertain Docker mutation
retains the lease until its captured immutable container ID is quiescent.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import threading
import time
import uuid


WORKTREE = Path(__file__).resolve().parents[2]
HELPER = Path("C:/Users/Moe/.codex/visualizations/2026/10/01/01a0f62b-3e5e-7973-965f-1731616886cd/pr-review-automation/local-ci/controller.py")
HELPER_SHA = "984cc9f0cdd5f3ce2e74f64f7d16cea2a7a39f36f6c025493c6e7b05b4cae2a7"
LOCK = HELPER.parent / "repository-ci.lock.json"
HEARTBEAT = HELPER.parent / "local-runtime-heartbeat.json"
BANK_VOLUME = "hackathon-banking-mcp-state"
FLUJO_REVISION = "0ba62296520a505e6d71eddf5aa650691f3dc311"
# Actual component failure precedes provider use. A moving image or authored
# passing receipt must not turn this observed source into a qualified release.
UNQUALIFIED_SOURCE = {"676466111e7013136488b0aa7a0cf1ecbee45a86"}
GIB = 1024 ** 3
KERNEL_FIELDS = ("actualDockerKernel", "uidAndGroups", "userPidNamespace",
                 "wrappedRawCliHelp", "privateSentinelsDenied", "controlsMutationDenied",
                 "freshInvocationHomeOnly", "immutableProfileReadback",
                 "readOnlyHostBindBoundary", "readOnlyDataBindBoundary",
                 "crossUidSupervisorSignals")


class Refused(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def emit(event, **fields):
    try:
        print(json.dumps({"event": event, "controller_pid": os.getpid(), **fields}, sort_keys=True), flush=True)
    except Exception:
        pass  # A closed output pipe cannot release a live runtime's lease.


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def hex_value(value, count=64):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{%d}" % count, value) is not None


def same_path(first, second):
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def environment(extra=None):
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
               "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
               "PROGRAMDATA", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG"}
    result = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    result.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    result.update(extra or {})
    return result


def command(arguments, *, extra=None, cwd=WORKTREE, timeout=90):
    result = subprocess.run(arguments, cwd=cwd, env=environment(extra), capture_output=True,
                            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    require(len(result.stdout) <= 2 * 1024 * 1024 and len(result.stderr) <= 65536, "command_output_limit")
    return result


def checked(arguments, **options):
    result = command(arguments, **options)
    require(result.returncode == 0, "read_only_command_failed")
    return result.stdout.decode("utf-8-sig").strip()


def json_command(arguments, **options):
    return json.loads(checked(arguments, **options))


def load_helper():
    raw = HELPER.read_bytes()
    require(sha(raw) == HELPER_SHA, "shared_helper_hash_changed")
    spec = importlib.util.spec_from_file_location("owned_actual_local_lease", HELPER)
    require(spec is not None, "shared_helper_import_unavailable")
    module = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(HELPER), "exec"), module.__dict__)
    return module


def private_acl(filename):
    """Check Windows ACL authority; do not invent Unix modes for host binds."""
    require(os.name == "nt", "windows_host_required")
    # The path is a separate argument, not interpolated PowerShell source.
    script = ("$ErrorActionPreference='Stop';try{$p=$env:SAVIA_LOCAL_ACL_PATH;$a=Get-Acl -LiteralPath $p;"
              "$u=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;"
              "$ok=@($u,'S-1-5-18','S-1-5-32-544');"
              "$bad=@($a.Access|Where-Object {$_.AccessControlType -eq 'Allow' -and "
              "$ok -notcontains $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value});"
              "if($bad.Count -ne 0 -or $ok -notcontains $a.GetOwner([Security.Principal.SecurityIdentifier]).Value){exit 1};"
              "exit 0}catch{exit 1}")
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    require(command(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                    extra={"SAVIA_LOCAL_ACL_PATH": str(filename)}, timeout=15).returncode == 0,
            "private_host_acl_required")


def regular(filename, maximum=2 * 1024 * 1024):
    path = Path(filename)
    require(path.is_absolute() and not str(path).startswith("\\\\"), "absolute_local_path_required")
    before = path.lstat()
    require(path.is_file() and not path.is_symlink() and before.st_nlink == 1
            and not getattr(before, "st_file_attributes", 0) & 0x400
            and before.st_size <= maximum and same_path(path.resolve(), path), "regular_unlinked_file_required")
    return path, before


def raw_file(filename, *, maximum=2 * 1024 * 1024):
    path, before = regular(filename, maximum)
    raw = path.read_bytes()
    after = path.lstat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, len(raw), after.st_mtime_ns, after.st_ctime_ns), "input_drift")
    return raw


def artifact(reference, *, private=True):
    require(isinstance(reference, dict) and set(reference) == {"path", "sha256"}
            and hex_value(reference["sha256"]), "approved_artifact_reference_required")
    if private:
        private_acl(reference["path"])
    raw = raw_file(reference["path"])
    require(sha(raw) == reference["sha256"], "approved_artifact_changed")
    return json.loads(raw)


def committed_source(revision):
    require(hex_value(revision, 40) and checked(["git", "rev-parse", "HEAD"]) == revision,
            "committed_companion_revision_changed")
    require(not checked(["git", "status", "--porcelain"]), "companion_worktree_dirty")


def inspect_container(identifier):
    require(hex_value(identifier), "full_container_id_required")
    result = command(["docker", "container", "inspect", identifier], timeout=20)
    if result.returncode:
        if b"No such container:" in result.stderr or b"No such object:" in result.stderr:
            return None
        raise Refused("docker_observation_unavailable")
    values = json.loads(result.stdout)
    require(len(values) == 1 and values[0].get("Id") == identifier, "container_metadata_invalid")
    return values[0]


def effective_limits(container):
    host = container["HostConfig"]
    return (host.get("Memory") == 2 * GIB and host.get("MemorySwap") == 2 * GIB
            and host.get("NanoCpus") == 2_000_000_000 and host.get("PidsLimit") == 512
            and host.get("ReadonlyRootfs") is True and host.get("RestartPolicy", {}).get("Name") == "no"
            and host.get("Privileged") is False
            and sorted(host.get("CapAdd") or []) == sorted(["CHOWN", "FOWNER", "DAC_OVERRIDE", "SETUID", "SETGID", "KILL"])
            and host.get("CapDrop") == ["ALL"]
            and "no-new-privileges:true" in (host.get("SecurityOpt") or [])
            and "seccomp=unconfined" in (host.get("SecurityOpt") or [])
            and host.get("PortBindings") == {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "43800"}]})


def mount_contract(container, spec):
    expected = {
        "/data": ("volume", spec["nativeVolume"]["name"], True),
        "/data/banking-state": ("volume", BANK_VOLUME, True),
        "/opt/local-native": ("bind", str(WORKTREE / "deploy/local-banking"), False),
        "/run/local-owner/host": ("bind", str(LOCK.parent), False),
        "/run/local-bank/data": ("bind", spec["data"]["root"], False),
    }
    mounts = {item["Destination"]: item for item in container.get("Mounts", []) if item.get("Type") != "tmpfs"}
    if set(mounts) != set(expected):
        return False
    for target, (kind, source, writable) in expected.items():
        actual = mounts[target]
        if actual.get("Type") != kind or actual.get("RW") is not writable:
            return False
        if kind == "volume" and actual.get("Name") != source:
            return False
        if kind == "bind" and not same_path(actual.get("Source", ""), source):
            return False
    return True


def owned_identity(container, spec, owner, identifier):
    if container is None or container.get("Id") != identifier or identifier == spec["compose"]["baselineContainerId"]:
        return False
    labels = container.get("Config", {}).get("Labels") or {}
    required = {"com.docker.compose.project": "hackathon-banking", "com.docker.compose.service": "frontend",
                "io.savia.local-native.scope": "actual-retained-existing-frontend",
                "io.savia.local-native.application": spec["applicationRevision"],
                "io.savia.local-native.companion": spec["companionRevision"],
                "io.savia.local-native.lease-owner": owner}
    return (all(labels.get(key) == value for key, value in required.items())
            and container.get("Image") == spec["image"]["id"]
            and container.get("Config", {}).get("Image") == spec["image"]["reference"]
            and same_path(labels.get("com.docker.compose.project.working_dir", ""), spec["compose"]["workingDirectory"]))


def owned(container, spec, owner, identifier):
    return (owned_identity(container, spec, owner, identifier)
            and container.get("Config", {}).get("Entrypoint") == ["tini", "--", "node", "/opt/local-native/native-local.mjs"]
            and effective_limits(container) and mount_contract(container, spec))


def check_consumers(spec, allowed_id=None):
    ids = checked(["docker", "ps", "-aq", "--no-trunc", "--filter", "volume=" + BANK_VOLUME]).splitlines()
    require(len(ids) <= 64, "canonical_consumer_limit")
    retired = {item["id"]: item["imageId"] for item in spec["_retirement"]["retiredRwConsumers"]}
    for identifier in ids:
        require(hex_value(identifier), "canonical_consumer_full_id_required")
        value = inspect_container(identifier)
        if value is None:
            continue
        if any(item.get("Type") == "volume" and item.get("Name") == BANK_VOLUME and item.get("RW")
               for item in value.get("Mounts", [])):
            if identifier == allowed_id:
                continue
            # A retained RW mount is not itself a bank writer. Only exact
            # original-owner retired IDs/images are excepted, never unknown ones.
            require(retired.get(identifier) == value.get("Image"), "unreviewed_canonical_rw_consumer")
    observe_retirement(spec)


def observe_retirement(spec):
    """Require an actual reviewed read-only guard observation, not ID/image alone."""
    retirement = spec["_retirement"]
    observer = retirement.get("guardObserver", {})
    require(set(observer) == {"path", "sha256"} and hex_value(observer.get("sha256")),
            "actual_retirement_guard_observer_unimplemented")
    # Preflight observes retirement before run() freezes the full release. Hold
    # the observer and its ancestors before its first digest read, including
    # plan-only calls, so Python cannot reopen replacement bytes after approval.
    # Keep the original interpreter, script path, __file__ and argv contract.
    frozen = FrozenInputs()
    try:
        frozen.freeze(observer["path"])
        require(sha(raw_file(observer["path"])) == observer["sha256"], "retirement_observer_source_changed")
        result = json_command([sys.executable, "-I", "-B", observer["path"],
                               "--retirement-proof", spec["evidence"]["retirement"]["path"],
                               "--retirement-proof-sha256", spec["evidence"]["retirement"]["sha256"]], timeout=20)
    finally:
        frozen.close()
    expected = [{"id": item["id"], "imageId": item["imageId"], "guardMechanismSha256": item["guardMechanismSha256"]}
                for item in retirement["retiredRwConsumers"]]
    require(result.get("schema") == "savia-local-native-retirement-observation/v1"
            and result.get("method") == "actual-docker-read-only"
            and result.get("observerSha256") == observer["sha256"]
            and result.get("dockerDaemonId") == retirement["dockerDaemonId"]
            and result.get("authorityProofSha256") == retirement["authorityProofSha256"]
            and result.get("canonicalBankVolume") == BANK_VOLUME
            and result.get("state") == "authority-disabled-no-respawn"
            and result.get("consumers") == expected, "actual_retirement_guard_not_observed")


def retired_baseline(spec):
    compose = spec["compose"]
    value = inspect_container(compose["baselineContainerId"])
    require(value is not None and value.get("Image") == compose["baselineImageId"]
            and not value["State"]["Running"] and not value["State"].get("Restarting"),
            "original_owner_retired_baseline_must_still_exist")
    labels = value["Config"].get("Labels") or {}
    require(labels.get("com.docker.compose.project") == "hackathon-banking"
            and labels.get("com.docker.compose.service") == "frontend"
            and same_path(labels.get("com.docker.compose.project.working_dir", ""), compose["workingDirectory"]),
            "baseline_compose_provenance_changed")
    files = labels.get("com.docker.compose.project.config_files", "").split(",")
    require(len(files) == len(compose["files"]) and all(same_path(path, item["path"])
            and sha(raw_file(path)) == item["sha256"] for path, item in zip(files, compose["files"])),
            "original_compose_files_changed")
    return value


def preflight(spec, module):
    require(spec.get("schema") == "savia-local-native-controller/v1", "release_spec_schema_required")
    require(spec.get("applicationRevision") not in UNQUALIFIED_SOURCE, "source_has_observed_provider_component_failure")
    committed_source(spec["companionRevision"])
    companion = WORKTREE / "deploy/local-banking"
    raw = raw_file(companion / "native-local.mjs")
    match = re.search(rb"const REVISION = '([a-f0-9]{40})';", raw)
    require(match and match[1].decode() == spec["applicationRevision"], "launcher_application_pin_changed")
    require(re.fullmatch(r"registry\.fly\.io/flujo-factored-2026@sha256:[a-f0-9]{64}", spec["image"]["reference"])
            and re.fullmatch(r"sha256:[a-f0-9]{64}", spec["image"]["id"]), "immutable_image_required")
    image = json_command(["docker", "image", "inspect", spec["image"]["reference"]])[0]
    require(image["Id"] == spec["image"]["id"] and spec["image"]["reference"] in image.get("RepoDigests", []),
            "installed_image_identity_changed")
    ev = {name: artifact(spec["evidence"][name]) for name in
          ("approvalTemplate", "buildReceipt", "transitionReceipt", "kernel", "preparation", "retirement")}
    approval, build, receipt, kernel, prepared, retirement = (ev[name] for name in
          ("approvalTemplate", "buildReceipt", "transitionReceipt", "kernel", "preparation", "retirement"))
    require("runtimeLease" not in approval and approval.get("schema") == "savia-local-retained-release/v1"
            and approval.get("applicationRevision") == spec["applicationRevision"]
            and approval.get("companionRevision") == spec["companionRevision"]
            and approval.get("approvedImage") == spec["image"]["reference"]
            and approval.get("canonicalBankVolume") == BANK_VOLUME
            and approval.get("nativeStateVolume") == spec["nativeVolume"]["name"]
            and approval.get("originalBankAuthorityRetired") is True
            and approval.get("enableSimulatedIntake") is True, "reviewed_unbound_approval_template_required")
    require(all(sha(raw_file(companion / name)) == approval.get("companionFiles", {}).get(name)
                for name in ("native-local.mjs", "local-proxy.mjs")), "companion_bytes_changed")
    require(build.get("applicationRevision") == spec["applicationRevision"] and build.get("flujoRevision") == FLUJO_REVISION
            and build.get("sourceInputsVerified") is True
            and build.get("sourceManifestSha256") == approval.get("sourceManifestSha256"), "reviewed_build_receipt_required")
    require(approval.get("transitionReceiptSha256") == spec["evidence"]["transitionReceipt"]["sha256"]
            and receipt.get("schema") == "dispute-retained-transition/v1"
            and receipt.get("bank_path") == "/data/banking-state/banking.db"
            and receipt.get("native_state_dir") == "/data/banking-state"
            and receipt.get("native_authority_dir") == "/data/native-authority/control"
            and receipt.get("source", {}).get("root") == "/opt/joined", "retained_transition_receipt_required")
    start = receipt.get("operator_proof", {}).get("coverage_start")
    require(type(start) is int and 0 < start <= int(time.time()) - 86400, "actual_local_24h_history_required")
    require(approval.get("kernelQualificationSha256") == spec["evidence"]["kernel"]["sha256"]
            and kernel.get("schema") == "savia-local-native-kernel-qualification/v1" and kernel.get("status") == "pass"
            and kernel.get("image") == spec["image"]["reference"] and kernel.get("applicationRevision") == spec["applicationRevision"]
            and kernel.get("nativeWrapperSha256") == build.get("nativeWrapperSha256")
            and kernel.get("nativeBinarySha256") == build.get("nativeBinarySha256")
            and all(kernel.get(key) is True for key in KERNEL_FIELDS), "actual_local_kernel_qualification_required")
    daemon = json_command(["docker", "info", "--format", "{{json .ID}}"])
    require(isinstance(daemon, str) and daemon and kernel.get("dockerDaemonId") == daemon,
            "actual_qualified_docker_daemon_required")
    require(prepared.get("schema") == "savia-local-native-preparation/v1"
            and prepared.get("image") == spec["image"]["reference"] and prepared.get("imageId") == spec["image"]["id"]
            and prepared.get("applicationRevision") == spec["applicationRevision"]
            and prepared.get("companionRevision") == spec["companionRevision"]
            and prepared.get("nativeVolume") == spec["nativeVolume"]["name"]
            and prepared.get("approvalTemplateSha256") == spec["evidence"]["approvalTemplate"]["sha256"]
            and prepared.get("transitionReceiptSha256") == spec["evidence"]["transitionReceipt"]["sha256"]
            and prepared.get("kernelSha256") == spec["evidence"]["kernel"]["sha256"]
            and prepared.get("dockerDaemonId") == daemon
            and prepared.get("retiredFrontendId") == spec["compose"]["baselineContainerId"]
            and prepared.get("retiredFrontendImageId") == spec["compose"]["baselineImageId"], "actual_prepared_linux_receipt_required")
    verified = prepared.get("retainedVerifier", {})
    require(verified.get("method") == "actual-installed-read-only" and verified.get("exitCode") == 0
            and verified.get("sourceManifestSha256") == build.get("sourceManifestSha256")
            and verified.get("receiptSha256") == spec["evidence"]["transitionReceipt"]["sha256"], "actual_retained_verifier_receipt_required")
    authority = receipt.get("operator_proof", {}).get("authority_artifact", {}).get("sha256")
    require(retirement.get("schema") == "savia-local-bank-authority-retirement/v1"
            and retirement.get("canonicalBankVolume") == BANK_VOLUME and hex_value(authority)
            and retirement.get("dockerDaemonId") == daemon
            and retirement.get("authorityProofSha256") == authority
            and isinstance(retirement.get("retiredRwConsumers"), list)
            and all(hex_value(item.get("id")) and re.fullmatch(r"sha256:[a-f0-9]{64}", item.get("imageId", ""))
                    and hex_value(item.get("guardMechanismSha256"))
                    for item in retirement["retiredRwConsumers"]), "original_owner_retirement_proof_required")
    spec["_retirement"], spec["_approval"] = retirement, approval
    private_acl(LOCK.parent)
    private_acl(spec["controlDirectory"])
    require(not HEARTBEAT.exists(), "existing_runtime_heartbeat_retained")
    require(sha(raw_file(spec["bindingPublisher"]["path"])) == spec["bindingPublisher"]["sha256"], "reviewed_binding_publisher_required")
    volume = json_command(["docker", "volume", "inspect", spec["nativeVolume"]["name"]])[0]
    require(volume.get("Labels", {}).get(spec["nativeVolume"]["ownerLabelKey"]) == spec["nativeVolume"]["ownerLabelValue"],
            "prepared_native_volume_ownership_required")
    canonical_volume = json_command(["docker", "volume", "inspect", BANK_VOLUME])[0]  # no creation
    # Creation metadata identifies this existing volume; it is never a 24h
    # history anchor or a substitute for retained source/coverage evidence.
    require(prepared.get("canonicalVolumeIdentity") == {key: canonical_volume.get(key) for key in
            ("Name", "CreatedAt", "Driver", "Scope")}, "retained_canonical_volume_identity_changed")
    compose = spec["compose"]
    require(compose["project"] == "hackathon-banking" and hex_value(compose["baselineContainerId"]), "existing_frontend_provenance_required")
    baseline = retired_baseline(spec)
    old_mounts = {item["Destination"]: item for item in baseline.get("Mounts", [])}
    spec["_baseEnvironment"] = {}
    for key, target in (("BANKING_DATA_DIR", "/banking-data"), ("BANKING_CONFIG_FILE", "/banking-config/frontend.json"),
                        ("BANKING_SIGNER_FILE", "/banking-config/frontend-signer.pem")):
        item = old_mounts.get(target, {})
        require(item.get("Type") == "bind" and item.get("RW") is False, "original_frontend_bind_provenance_required")
        spec["_baseEnvironment"][key] = item["Source"]
    check_consumers(spec)
    memory = module.read_windows_memory()
    require(memory["available_physical_bytes"] >= 6 * GIB and memory["available_commit_bytes"] >= 16 * GIB,
            "actual_6gib_physical_16gib_commit_guard")
    return memory


class FrozenInputs:
    """Windows read handles deny write/delete sharing until lease cleanup."""
    def __init__(self):
        self.handles = []
        self.paths = set()
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                           ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        self.kernel.CreateFileW.restype = ctypes.c_void_p
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]

    def hold(self, path):
        path = Path(path)
        key = os.path.normcase(str(path.absolute()))
        if key in self.paths:
            return
        stamp = path.lstat()
        require(not path.is_symlink() and not getattr(stamp, "st_file_attributes", 0) & 0x400, "reparse_input_refused")
        # FILE_READ_ATTRIBUTES alone is exempt from sharing restrictions. A
        # genuine data-read handle enforces exclusion of existing/future writers.
        handle = self.kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x02000000 | 0x00200000, None)
        require(handle not in (None, ctypes.c_void_p(-1).value), "exclusive_read_freeze_unavailable")
        self.handles.append(handle)
        self.paths.add(key)

    def freeze(self, path):
        path = Path(path)
        for parent in reversed(path.parents):
            if parent != Path(parent.anchor):
                self.hold(parent)
        self.hold(path)

    def close(self):
        for handle in reversed(self.handles):
            self.kernel.CloseHandle(handle)
        self.handles.clear()


def freeze_inputs(spec, frozen):
    inventory = artifact(spec["data"]["inventory"])
    require(inventory.get("schema") == "recovered-real-dataset-closure/v1"
            and inventory.get("file_count") == 150 and inventory.get("total_source_bytes") == 932297878
            and len(inventory.get("files", [])) == 150
            and inventory.get("build_id") == spec["_approval"]["dataset"].get("buildId")
            and inventory.get("source_fingerprint") == spec["_approval"]["dataset"].get("sourceFingerprint")
            and spec["data"]["inventory"]["sha256"] == spec["_approval"]["dataset"].get("inventorySha256"),
            "actual_complete_dataset_inventory_required")
    root = Path(spec["data"]["root"])
    require(root.is_absolute() and root.is_dir(), "actual_data_root_required")
    seen, total = set(), 0
    for item in inventory["files"]:
        relative = PurePosixPath(item["path"])
        require(not relative.is_absolute() and ".." not in relative.parts and "\\" not in item["path"]
                and str(relative) == item["path"] and item["path"] not in seen
                and hex_value(item["sha256"]), "dataset_allowlist_invalid")
        filename = root.joinpath(*relative.parts)
        require(filename.resolve().is_relative_to(root.resolve()), "dataset_path_escape")
        frozen.freeze(filename)
        _, before = regular(filename, 2 ** 63 - 1)
        require(before.st_size == item["bytes"], "dataset_size_changed")
        digest = hashlib.sha256()
        with filename.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        after = filename.lstat()
        require(digest.hexdigest() == item["sha256"]
                and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                "dataset_bytes_changed")
        seen.add(item["path"])
        total += before.st_size
    require(total == inventory["total_source_bytes"] and "CURRENT" in seen, "dataset_closure_changed")
    for reference in [*spec["compose"]["files"], spec["data"]["inventory"], spec["bindingPublisher"],
                      spec["_retirement"]["guardObserver"], *spec["evidence"].values()]:
        frozen.freeze(reference["path"])
        require(sha(raw_file(reference["path"])) == reference["sha256"], "reviewed_input_changed_before_lease")
    for name in ("native-local.mjs", "local-proxy.mjs", "compose.native.yaml", "native-controller.py"):
        frozen.freeze(WORKTREE / "deploy/local-banking" / name)
    require((root / "CURRENT").read_text().strip() == spec["_approval"]["dataset"]["buildId"], "actual_current_changed")


class Heartbeat:
    def __init__(self, lease, owner, revision):
        self.lease, self.owner, self.revision = lease, owner, revision
        self.stopping, self.failed = threading.Event(), threading.Event()
        self.payload = None
        self.thread = threading.Thread(target=self.loop, name="owned-runtime-heartbeat", daemon=True)

    def write(self):
        require(LOCK.read_bytes() == self.lease.payload, "shared_lease_owner_changed")
        payload = canonical({"owner_token": self.owner, "controller_pid": os.getpid(), "head": self.revision,
                             "status": "active", "canonical_bank_volume": BANK_VOLUME,
                             "heartbeat_at": datetime.now(timezone.utc).isoformat()})
        if self.payload is None:
            with HEARTBEAT.open("xb") as stream:
                stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        else:
            require(HEARTBEAT.read_bytes() == self.payload, "runtime_heartbeat_owner_changed")
            temporary = HEARTBEAT.with_name(".heartbeat-" + self.owner + "-" + uuid.uuid4().hex)
            try:
                with temporary.open("xb") as stream:
                    stream.write(payload); stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, HEARTBEAT)
            finally:
                temporary.unlink(missing_ok=True)
        self.payload = payload

    def start(self):
        self.write()
        self.thread.start()

    def loop(self):
        while not self.stopping.wait(5):
            try:
                self.write()
            except Exception:
                self.failed.set()
                return

    def close(self):
        self.stopping.set()
        if self.thread.ident:
            self.thread.join(timeout=10)
        if self.payload is not None and HEARTBEAT.exists() and HEARTBEAT.read_bytes() == self.payload:
            HEARTBEAT.unlink()


def compose_args(spec):
    args = ["docker", "compose", "--project-name", "hackathon-banking", "--project-directory", spec["compose"]["workingDirectory"]]
    for item in spec["compose"]["files"]:
        args += ["--file", item["path"]]
    return args + ["--file", str(WORKTREE / "deploy/local-banking/compose.native.yaml")]


def compose_environment(spec, owner):
    return {**spec["_baseEnvironment"], "FLUJO_NETWORK": spec["compose"]["flujoNetwork"],
            "SAVIA_LOCAL_JOINED_IMAGE": spec["image"]["reference"], "SAVIA_LOCAL_NATIVE_VOLUME": spec["nativeVolume"]["name"],
            "SAVIA_LOCAL_COMPANION_REVISION": spec["companionRevision"], "SAVIA_LOCAL_LEASE_OWNER": owner,
            "SAVIA_LOCAL_COMPANION_DIR": str(WORKTREE / "deploy/local-banking"),
            "SAVIA_LOCAL_REAL_DATA": spec["data"]["root"], "SAVIA_LOCAL_HOST_LEASE_DIR": str(LOCK.parent)}


def effective_compose(config, spec):
    """Refuse unsafe resources/mounts before Compose's first daemon mutation."""
    app = config.get("services", {}).get("frontend", {})
    require(config.get("name") == "hackathon-banking" and app.get("image") == spec["image"]["reference"]
            and app.get("entrypoint") == ["tini", "--", "node", "/opt/local-native/native-local.mjs"]
            and app.get("mem_limit") == 2 * GIB and app.get("memswap_limit") == 2 * GIB
            and float(app.get("cpus", 0)) == 2 and app.get("pids_limit") == 512
            and app.get("read_only") is True and app.get("restart") == "no"
            and not app.get("privileged", False) and app.get("cap_drop") == ["ALL"]
            and app.get("user", "") in ("", "0", "root", "0:0")
            and sorted(app.get("cap_add", [])) == sorted(["CHOWN", "FOWNER", "DAC_OVERRIDE", "SETUID", "SETGID", "KILL"])
            and "no-new-privileges:true" in app.get("security_opt", [])
            and "seccomp=unconfined" in app.get("security_opt", []), "effective_compose_resource_boundary_changed")
    require(sorted(app.get("tmpfs", [])) == sorted(["/tmp:size=384m,mode=1777", "/run:size=64m,mode=0755"]),
            "effective_compose_tmpfs_boundary_changed")
    require(set(app.get("networks", {})) == {"default", "flujo"}
            and config.get("networks", {}).get("flujo", {}).get("external") is True
            and config["networks"]["flujo"].get("name") == spec["compose"]["flujoNetwork"],
            "existing_frontend_network_provenance_changed")
    ports = app.get("ports", [])
    require(len(ports) == 1 and ports[0].get("host_ip") == "127.0.0.1"
            and ports[0].get("target") == 8080 and str(ports[0].get("published")) == "43800"
            and ports[0].get("protocol") == "tcp", "effective_compose_public_port_changed")
    binds = {"/opt/local-native": str(WORKTREE / "deploy/local-banking"),
             "/run/local-owner/host": str(LOCK.parent), "/run/local-bank/data": spec["data"]["root"]}
    volumes = {"/data": spec["nativeVolume"]["name"], "/data/banking-state": BANK_VOLUME}
    mounts = app.get("volumes", [])
    require(len(mounts) == 5 and len({item.get("target") for item in mounts}) == 5, "effective_compose_mount_count_changed")
    for item in mounts:
        target = item.get("target")
        if target in binds:
            require(item.get("type") == "bind" and item.get("read_only") is True
                    and same_path(item.get("source", ""), binds[target])
                    and item.get("bind", {}).get("create_host_path") is False, "effective_compose_read_only_bind_changed")
        else:
            declaration = config.get("volumes", {}).get(item.get("source"), {})
            require(target in volumes and item.get("type") == "volume" and not item.get("read_only", False)
                    and declaration.get("external") is True and declaration.get("name") == volumes[target],
                    "effective_compose_owned_volume_changed")


def binding(spec, owner, directory, stopped):
    approval = {**spec["_approval"], "runtimeLease": {"ownerToken": owner, "controllerPid": os.getpid()}}
    expected = sha(canonical(approval))
    request = {"schema": "savia-local-native-owner-binding-request/v1", "owner_token": owner,
               "controller_pid": os.getpid(), "head": spec["companionRevision"], "approval_sha256": expected,
               "preparation_sha256": spec["evidence"]["preparation"]["sha256"]}
    (directory / "binding-request.json").write_bytes(canonical(request))
    emit("owner_binding_pending", owner_token=owner, head=spec["companionRevision"],
         binding_request=str(directory / "binding-request.json"), binding_receipt=str(directory / "binding.json"), deadline_seconds=60)
    deadline = time.monotonic() + 60
    while not stopped() and time.monotonic() < deadline:
        target = directory / "binding.json"
        if target.exists():
            private_acl(target)
            value = json.loads(raw_file(target, maximum=16384))
            require(value.get("schema") == "savia-local-native-owner-binding/v1"
                    and all(value.get(key) == expected_value for key, expected_value in
                            {"owner_token": owner, "controller_pid": os.getpid(), "head": spec["companionRevision"],
                             "image": spec["image"]["reference"], "native_volume": spec["nativeVolume"]["name"],
                             "preparation_sha256": spec["evidence"]["preparation"]["sha256"],
                             "publisher_sha256": spec["bindingPublisher"]["sha256"], "approval_sha256": expected}.items()),
                    "owner_binding_receipt_mismatch")
            require(value.get("inspection") == {"method": "actual-linux-readback", "path": "/data/private/local-native/approval.json",
                    "uid": 0, "gid": 0, "mode": 0o600, "sha256": expected, "volume": spec["nativeVolume"]["name"]},
                    "actual_linux_owner_binding_readback_required")
            return
        time.sleep(0.5)
    raise Refused("owner_binding_deadline_or_stop")


def signal_request(path, owner, revision, identifier=None):
    raw = raw_file(path, maximum=4096).strip()
    if not raw:
        return None
    value = json.loads(raw)
    require(set(value) == {"owner_token", "controller_pid", "head", "container_id", "request_id"}
            and value["owner_token"] == owner and value["controller_pid"] == os.getpid()
            and value["head"] == revision and value["container_id"] == identifier
            and str(uuid.UUID(value["request_id"])) == value["request_id"], "signal_owner_proof_invalid")
    return value["request_id"]


def discover(spec, owner):
    args = ["docker", "ps", "-aq", "--no-trunc", "--filter", "label=com.docker.compose.project=hackathon-banking",
            "--filter", "label=com.docker.compose.service=frontend", "--filter", "label=io.savia.local-native.lease-owner=" + owner]
    identifiers = checked(args).splitlines()
    require(len(identifiers) <= 1, "owned_container_identity_ambiguous")
    if not identifiers:
        return None
    identifier = identifiers[0]
    value = inspect_container(identifier)
    # Prove authorship separately from safety so a newly created owned ID with
    # unsafe limits/mounts can still be stopped. Never adopt the baseline ID.
    require(owned_identity(value, spec, owner, identifier), "owned_container_identity_mismatch")
    return identifier


def quiescent(value):
    return value is None or value["State"].get("Running") is False and value["State"].get("Restarting") is False


def cleanup_settled(value, launch_acknowledged):
    """A lost up response cannot turn a not-yet-started ID into exit proof."""
    if value is None:
        return True  # This captured immutable ID cannot be created again.
    if not quiescent(value):
        return False
    if launch_acknowledged:
        return True
    started = value["State"].get("StartedAt")
    try:
        return (isinstance(started, str)
                and datetime.fromisoformat(started.replace("Z", "+00:00"))
                > datetime(1970, 1, 1, tzinfo=timezone.utc))
    except (ValueError, TypeError):
        return False


def stop_owned(spec, owner, identifier, *, launch_acknowledged):
    while True:
        try:
            value = inspect_container(identifier)
            if value is None:
                return
            require(owned_identity(value, spec, owner, identifier), "cleanup_identity_changed")
            if cleanup_settled(value, launch_acknowledged):
                return
            if quiescent(value):
                # A pending daemon start may still follow this created snapshot.
                # Keep both heartbeat and lease until start/exit or ID absence.
                emit("lease_retained_launch_settlement_pending", container_id=identifier)
            else:
                command(["docker", "container", "stop", "--time", "30", identifier], timeout=50)
        except Exception as error:
            emit("lease_retained_cleanup_pending", container_id=identifier, reason=error.args[0] if isinstance(error, Refused) else "docker_uncertain")
        time.sleep(5)


def restart_owned(spec, owner, identifier, stopped):
    before = inspect_container(identifier)
    require(owned(before, spec, owner, identifier) and before["State"]["Running"], "owned_running_container_required")
    if stopped():
        return
    try:
        result = command(["docker", "container", "restart", "--time", "30", identifier], timeout=90)
        acknowledged = result.returncode == 0
    except Exception:
        acknowledged = False
    while True:
        try:
            value = inspect_container(identifier)
            if value is None:
                return
            require(owned(value, spec, owner, identifier), "restart_identity_changed")
            changed = value["State"].get("StartedAt") != before["State"].get("StartedAt")
            if not value["State"].get("Restarting") and (acknowledged or changed):
                emit("restart_completed", container_id=identifier, same_container=True,
                     running=value["State"]["Running"], volume_retained=True, acceptance="pending")
                return
            # Stop cannot hand an uncertain daemon restart's lease back before
            # its start phase settles. It takes priority immediately afterward.
        except Exception:
            pass
        time.sleep(2)


def run(spec, module):
    require(not LOCK.exists(), "existing_shared_lease_retained")
    frozen = FrozenInputs()
    try:
        freeze_inputs(spec, frozen)  # all existing preparation before the shared lease
        owner = uuid.uuid4().hex
        requested = threading.Event()
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), lambda *_: requested.set())
        with module.RepositoryLease(LOCK, spec["companionRevision"], owner) as lease:
            directory = Path(spec["controlDirectory"]) / ("native-owner-" + owner)
            directory.mkdir(exist_ok=False)
            for name in ("stop.json", "restart.json"):
                with (directory / name).open("xb"):
                    pass
            heartbeat = Heartbeat(lease, owner, spec["companionRevision"])
            identifier, attempted, fault, launch_acknowledged = None, False, None, False
            try:
                heartbeat.start()
                def stopped():
                    return (requested.is_set() or heartbeat.failed.is_set()
                            or signal_request(directory / "stop.json", owner, spec["companionRevision"], identifier) is not None)
                emit("lease_acquired", owner_token=owner, head=spec["companionRevision"],
                     stop_signal=str(directory / "stop.json"), restart_signal=str(directory / "restart.json"))
                binding(spec, owner, directory, stopped)
                committed_source(spec["companionRevision"])
                check_consumers(spec)
                memory = module.read_windows_memory()
                require(memory["available_physical_bytes"] >= 6 * GIB and memory["available_commit_bytes"] >= 16 * GIB,
                        "actual_6gib_physical_16gib_commit_guard")
                require(not stopped(), "stop_before_launch")
                retired_baseline(spec)
                extra = compose_environment(spec, owner)
                require(discover(spec, owner) is None, "fresh_owner_already_has_container")
                # Resolve privately to catch interpolation/Compose incompatibility
                # before the first daemon mutation. Never print effective config.
                config = json_command(compose_args(spec) + ["config", "--format", "json"], extra=extra)
                effective_compose(config, spec)
                require(not stopped(), "stop_before_launch")
                retired_baseline(spec)
                memory = module.read_windows_memory()
                require(memory["available_physical_bytes"] >= 6 * GIB and memory["available_commit_bytes"] >= 16 * GIB,
                        "actual_6gib_physical_16gib_commit_guard")
                attempted = True
                try:
                    # Let the mutating Compose client settle before a created/
                    # stopped ID can prove quiescence; heartbeat remains independent.
                    result = command(compose_args(spec) + ["up", "-d", "--no-build", "--no-deps", "--pull", "never",
                                                           "--force-recreate", "frontend"], extra=extra, timeout=None)
                    launch_acknowledged = result.returncode == 0
                    require(result.returncode == 0, "compose_launch_response_failed")
                    identifier = discover(spec, owner)
                    require(identifier is not None, "owned_container_not_confirmed")
                    require(owned(inspect_container(identifier), spec, owner, identifier), "owned_container_safety_contract_mismatch")
                except Exception:
                    # Late daemon creation is possible after a lost response. The
                    # UUID label and full contract, never its name, allow recovery.
                    while identifier is None:
                        try:
                            identifier = discover(spec, owner)
                        except Exception:
                            pass
                        if identifier is None:
                            emit("lease_retained_launch_uncertain", owner_token=owner)
                            time.sleep(10)
                    requested.set()
                    fault = "launch_response_failed_or_uncertain"
                emit("runtime_owned", container_id=identifier, public_origin="http://localhost:43800", acceptance="pending")
                handled = set()
                while not stopped():
                    try:
                        require(LOCK.read_bytes() == lease.payload, "shared_lease_owner_changed")
                        value = inspect_container(identifier)
                        if value is None:
                            fault = "owned_runtime_removed_without_stop"
                            break
                        require(owned(value, spec, owner, identifier), "runtime_identity_changed")
                        if quiescent(value):
                            fault = "owned_runtime_exited_without_stop"
                            break
                        check_consumers(spec, identifier)
                        restart = signal_request(directory / "restart.json", owner, spec["companionRevision"], identifier)
                        if restart is not None and restart not in handled and not stopped():
                            restart_owned(spec, owner, identifier, stopped)
                            handled.add(restart)
                    except Refused as error:
                        emit("lease_retained_monitor_pending", reason=str(error), container_id=identifier)
                        fault = str(error)
                        requested.set()  # retire only this exact owned ID
                    except Exception:
                        emit("lease_retained_observation_pending", container_id=identifier)
                    time.sleep(2)
                if heartbeat.failed.is_set():
                    fault = fault or "owned_heartbeat_failed"
                if fault:
                    emit("controller_runtime_fault", reason=fault, container_id=identifier)
                return 1 if fault else 0
            finally:
                # No mutation was attempted before binding, so failed handshakes
                # release without touching the original frontend or any volume.
                if attempted and identifier is None:
                    while identifier is None:
                        try:
                            identifier = discover(spec, owner)
                        except Exception:
                            pass
                        if identifier is None:
                            emit("lease_retained_launch_cleanup_uncertain", owner_token=owner)
                            time.sleep(10)
                if identifier is not None:
                    stop_owned(spec, owner, identifier, launch_acknowledged=launch_acknowledged)
                    emit("runtime_stopped", container_id=identifier, volumes_retained=True)
                heartbeat.close()
                emit("owned_lease_cleanup_complete", owner_token=owner, head=spec["companionRevision"])
    finally:
        frozen.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--spec-sha256", required=True)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    try:
        require(os.name == "nt", "windows_host_required")
        spec = artifact({"path": str(args.spec), "sha256": args.spec_sha256})
        module = load_helper()
        memory = preflight(spec, module)
        if not args.run:
            emit("plan_only", head=spec["companionRevision"], application_revision=spec["applicationRevision"],
                 image=spec["image"]["reference"], lease_present=LOCK.exists(), existing_frontend=True,
                 resource_guard_eligible=True, runtime_memory_gib=2, available_physical_bytes=memory["available_physical_bytes"],
                 available_commit_bytes=memory["available_commit_bytes"], runtime_activation=False)
            return 0
        return run(spec, module)
    except Exception as error:
        emit("controller_refused", reason=str(error) if isinstance(error, Refused) else "unavailable_or_invalid_release_input",
             error_type=type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
