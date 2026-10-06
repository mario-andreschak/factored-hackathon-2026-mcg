"""Qualify source admission without a Git checkout, account or provider."""
import hashlib
import json
from pathlib import Path
import shutil

from fastapi.testclient import TestClient
import pytest

from standalone.savia_whatsapp import runtime


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def write_manifests(root, *, source_updates=None, package_updates=None):
    files = {path.relative_to(root).as_posix(): digest(path.read_bytes())
             for path in root.rglob("*") if path.is_file() and path.name not in
             {"standalone-package.json", "source-manifest.json"}}
    rc_files = {name: value for name, value in files.items()
                if not name.startswith(("standalone/", "whatsapp-mcp/")) and name != ".dockerignore"}
    source = {"schema": "savia-public-rc-source/v1", "git_head": runtime.RC_REVISION,
              "git_tree": "a" * 40, "files": rc_files, "fiction_only": True, "flujo_built": False}
    source.update(source_updates or {})
    source_payload = json.dumps(source).encode()
    (root / "source-manifest.json").write_bytes(source_payload)
    files["source-manifest.json"] = digest(source_payload)
    package = {"schema": "savia-whatsapp-local-package/v1", "rc_revision": runtime.RC_REVISION,
               "whatsapp_mcp_revision": runtime.MCP_REVISION, "feature_revision": "b" * 40,
               "files": files, "real_bank_actions": False, "state_included": False, "secrets_included": False}
    package.update(package_updates or {})
    (root / "standalone-package.json").write_text(json.dumps(package))
    return package, source


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path / "bundle-without-git"
    source = runtime._REQUIRED_FEATURE | runtime._REQUIRED_MCP | {
        "deploy/rc/run.py", "banking_mcp/service.py", "frontend/server/voice.py",
        "whatsapp-mcp/public/index.html", ".dockerignore"}
    for name in source:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# harmless public source\n")
    (root / "deploy/rc/run.py").write_text(
        "import json\nfrom pathlib import Path\nEXECUTED = True\n"
        "def source_revision():\n"
        "    return json.loads((Path(__file__).resolve().parents[2] / 'source-manifest.json').read_text())['git_head']\n")
    write_manifests(root)
    monkeypatch.setattr(runtime, "ROOT", root)
    return root


def test_exported_bundle_and_installed_mcp_admit_without_git(bundle, tmp_path, monkeypatch):
    installed = tmp_path / "installed-mcp"
    shutil.copytree(bundle / "whatsapp-mcp", installed)
    # Compiled code/dependencies are qualified by the build, not falsely claimed
    # as immutable source in the export manifest.
    (installed / "dist").mkdir()
    (installed / "dist/index.js").write_text("// independently built artifact\n")
    def no_git(*args, **kwargs):
        pytest.fail("Bundle admission must not execute Git or a subprocess")
    monkeypatch.setattr(runtime.subprocess, "check_output", no_git)
    admitted = runtime.verified_bundle(installed)
    assert admitted == {"rc_revision": runtime.RC_REVISION, "whatsapp_mcp_revision": runtime.MCP_REVISION,
                        "feature_revision": "b" * 40,
                        "package_manifest_sha256": digest((bundle / "standalone-package.json").read_bytes())}
    assert runtime.rc_module().EXECUTED
    assert not (bundle / ".git").exists()


def test_checkout_refused_before_rc_execution_credentials_or_state(tmp_path, monkeypatch):
    root = tmp_path / "ordinary-checkout"
    root.mkdir()
    monkeypatch.setattr(runtime, "ROOT", root)
    def forbidden(*args, **kwargs):
        pytest.fail("Unadmitted source must not execute or access provider credentials")
    monkeypatch.setattr(runtime.importlib.util, "spec_from_file_location", forbidden)
    monkeypatch.setattr(runtime, "provider_key", forbidden)
    state = tmp_path / "untouched-state"
    with pytest.raises(runtime.BundleAdmissionError, match="export a fresh standalone package.*inside its bundle"):
        runtime.rc_module()
    with pytest.raises(runtime.BundleAdmissionError):
        runtime.create_control(state, tmp_path / "mcp", tmp_path / "provider.env")
    assert not state.exists()


@pytest.mark.parametrize("manifest,field,value", [
    ("package", "schema", "other/v1"), ("package", "rc_revision", "0" * 40),
    ("package", "whatsapp_mcp_revision", "0" * 40), ("package", "feature_revision", "dirty"),
    ("source", "schema", "other/v1"), ("source", "git_head", "0" * 40),
    ("package", "state_included", True), ("package", "secrets_included", True),
    ("source", "flujo_built", True), ("source", "fiction_only", False),
])
def test_manifest_source_contract_requires_qualified_pins_and_boundary(bundle, manifest, field, value):
    write_manifests(bundle, **{manifest + "_updates": {field: value}})
    with pytest.raises(runtime.BundleAdmissionError):
        runtime.verified_bundle()


@pytest.mark.parametrize("name", ["deploy/rc/run.py", "frontend/server/voice.py",
                                 "standalone/savia_whatsapp/whatsapp.py", "whatsapp-mcp/src/index.ts",
                                 "whatsapp-mcp/public/index.html", "source-manifest.json"])
def test_any_changed_packaged_source_is_rejected_before_rc_execution(bundle, name, monkeypatch):
    path = bundle / name
    path.write_bytes(path.read_bytes() + b"\n")
    def forbidden(*args, **kwargs):
        pytest.fail("A source mismatch must be rejected before loading RC code")
    monkeypatch.setattr(runtime.importlib.util, "spec_from_file_location", forbidden)
    with pytest.raises(runtime.BundleAdmissionError, match="hash mismatch"):
        runtime.rc_module()


def test_rc_hash_coverage_cannot_be_removed_from_source_manifest(bundle):
    _, source = write_manifests(bundle)
    del source["files"]["frontend/server/voice.py"]
    write_manifests(bundle, source_updates={"files": source["files"]})
    with pytest.raises(runtime.BundleAdmissionError, match="coverage disagree"):
        runtime.verified_bundle()


def test_mandatory_feature_source_cannot_be_removed_from_package_manifest(bundle):
    package, _ = write_manifests(bundle)
    del package["files"]["standalone/savia_whatsapp/runtime.py"]
    write_manifests(bundle, package_updates={"files": package["files"]})
    with pytest.raises(runtime.BundleAdmissionError, match="coverage disagree"):
        runtime.verified_bundle()


@pytest.mark.parametrize("name", [".", "../private.py", "/absolute.py", "C:/private.py", r"C:\private.py",
                                 "deploy//rc/extra.py", "deploy/./rc/extra.py"])
def test_manifest_paths_are_portable_and_cannot_escape_bundle(bundle, name):
    package, source = write_manifests(bundle)
    package["files"][name] = "0" * 64
    source["files"][name] = "0" * 64
    write_manifests(bundle, source_updates={"files": source["files"]})
    # Rehash the changed source manifest while retaining the unsafe source entry.
    package["files"]["source-manifest.json"] = digest((bundle / "source-manifest.json").read_bytes())
    (bundle / "standalone-package.json").write_text(json.dumps(package))
    with pytest.raises(runtime.BundleAdmissionError, match="Unsafe package source path"):
        runtime.verified_bundle()


@pytest.mark.parametrize("name", ["frontend/server/unlisted.py", "standalone/savia_whatsapp/unlisted.py",
                                 "whatsapp-mcp/src/unlisted.ts"])
def test_unmanifested_source_cannot_be_loaded_as_part_of_bundle(bundle, name):
    (bundle / name).write_text("# omitted source\n")
    with pytest.raises(runtime.BundleAdmissionError, match="absent from the package manifest"):
        runtime.verified_bundle()


def test_source_manifest_duplicate_fields_are_rejected(bundle):
    payload = (bundle / "source-manifest.json").read_text()
    payload = payload[:-1] + ',"git_head":"' + runtime.RC_REVISION + '"}'
    (bundle / "source-manifest.json").write_text(payload)
    with pytest.raises(runtime.BundleAdmissionError, match="Duplicate manifest fields"):
        runtime.verified_bundle()


@pytest.mark.parametrize("change", ["modified", "missing", "extra"])
def test_external_mcp_source_must_match_admitted_copy_before_key_access(bundle, tmp_path, monkeypatch, change):
    installed = tmp_path / "installed-mcp"
    shutil.copytree(bundle / "whatsapp-mcp", installed)
    target = installed / "src/index.ts"
    if change == "modified":
        target.write_text("// changed MCP\n")
    elif change == "missing":
        target.unlink()
    else:
        (installed / "src/unlisted.ts").write_text("// additional MCP source\n")
    monkeypatch.setattr(runtime, "provider_key", lambda _: pytest.fail("Admission precedes provider-key access"))
    state = tmp_path / "untouched-state"
    with pytest.raises(runtime.BundleAdmissionError):
        runtime.create_control(state, installed, None)
    assert not state.exists()


def test_regular_source_cannot_be_replaced_by_a_symlink(bundle, tmp_path):
    target = bundle / "frontend/server/voice.py"
    outside = tmp_path / "outside.py"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("This host cannot create file symlinks")
    with pytest.raises(runtime.BundleAdmissionError, match="Linked package source"):
        runtime.verified_bundle()


def test_source_directory_cannot_redirect_to_an_identical_external_tree(bundle, tmp_path):
    target = bundle / "frontend/server"
    outside = tmp_path / "external-server"
    shutil.move(target, outside)
    try:
        target.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("This host cannot create directory symlinks")
    with pytest.raises(runtime.BundleAdmissionError, match="Linked package source"):
        runtime.verified_bundle()


def test_rc_reported_revision_must_agree_after_independent_manifest_verification(bundle):
    (bundle / "deploy/rc/run.py").write_text("def source_revision():\n    return 'incorrect-runtime-ref'\n")
    write_manifests(bundle)
    with pytest.raises(runtime.BundleAdmissionError, match="Loaded RC source revision disagrees"):
        runtime.rc_module()


def test_status_reports_admitted_feature_and_manifest_and_starts_stopped(bundle, tmp_path, monkeypatch):
    class Process:
        def __init__(self, *args, **kwargs):
            self.dead = False
        def poll(self):
            return 0 if self.dead else None
        def terminate(self):
            self.dead = True
        def wait(self, *args):
            return 0
    monkeypatch.setattr(runtime, "ensure_ports_available", lambda: None)
    monkeypatch.setattr(runtime, "private_creation_policy", lambda: None)
    monkeypatch.setattr(runtime, "provider_key", lambda _: "")
    monkeypatch.setattr(runtime.subprocess, "Popen", Process)
    state = tmp_path / "offline-state"
    app = runtime.create_control(state, bundle / "whatsapp-mcp", None)
    with TestClient(app, base_url="http://127.0.0.1:43980") as client:
        status = client.get("/status").json()
        assert status["loaded_feature_revision"] == "b" * 40
        assert status["package_manifest_sha256"] == digest((bundle / "standalone-package.json").read_bytes())
        assert status["rc_source"] == runtime.RC_REVISION
        assert status["running"] is False
    assert not (state / "active.lock").exists()
