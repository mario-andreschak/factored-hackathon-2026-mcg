"""Export pinned public source plus the explicit standalone feature; never state."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import zipfile

from . import MCP_REVISION, RC_REVISION

ROOT = Path(__file__).resolve().parents[2]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def build_package(destination: Path, mcp_repo: Path):
    if destination.exists():
        raise ValueError("Use a fresh package destination")
    if git(mcp_repo, "rev-parse", MCP_REVISION).decode().strip() != MCP_REVISION:
        raise ValueError("Pinned MCP commit is missing")
    spec = importlib.util.spec_from_file_location("rc_export", ROOT / "deploy/rc/build_public_context.py")
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    exporter.export(destination, RC_REVISION)
    feature = Path(__file__).parent
    paths = [ROOT / "standalone/__init__.py", ROOT / "standalone/tests/test_whatsapp.py"]
    # A --state directory accidentally placed below this package must never be exported.
    names = ("__init__.py", "__main__.py", "runtime.py", "bridge.py", "savia.py", "whatsapp.py",
             "package.py", "README.md", "requirements.txt", "Dockerfile", ".dockerignore", "compose.yml",
             "control.html", "docs/video-notes.md", "docs/validation.json", "tests/test_bridge.py",
             "tests/test_savia.py", "tests/test_runtime.py", "tests/test_package.py", "tests/test_linux_runtime.py")
    paths += [feature / name for name in names if (feature / name).is_file()]
    for path in paths:
        if path.is_symlink() or any(parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction())
                                    for parent in path.parents if parent != ROOT and ROOT in parent.parents):
            raise ValueError("Symlink is not package source")
        relative = path.relative_to(ROOT)
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(path.read_bytes())
    (destination / ".dockerignore").write_bytes((feature / ".dockerignore").read_bytes())
    for entry in git(mcp_repo, "ls-tree", "-r", "-z", MCP_REVISION).split(b"\0"):
        if not entry:
            continue
        metadata, raw = entry.split(b"\t", 1)
        name = raw.decode()
        if not (name in {"package.json", "package-lock.json", "tsconfig.json", "LICENSE"} or name.startswith(("src/", "public/"))):
            continue
        if metadata.split()[0] not in {b"100644", b"100755"}:
            raise ValueError("Nonregular MCP source")
        output = destination / "whatsapp-mcp" / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(git(mcp_repo, "show", f"{MCP_REVISION}:{name}"))
    # A local-only compatibility overlay; the original MCP repository remains unchanged.
    baileys = destination / "whatsapp-mcp/src/services/baileys.ts"
    before = baileys.read_bytes()
    old = "Browsers.windows('Desktop') : Browsers.macOS('Desktop')"
    source = before.decode()
    if source.count(old) != 1:
        raise ValueError("Pinned MCP browser descriptor no longer matches the reviewed overlay")
    after = source.replace(old, "Browsers.windows('Chrome') : Browsers.macOS('Chrome')").encode()
    baileys.write_bytes(after)
    overlay = {"file": "whatsapp-mcp/src/services/baileys.ts", "kind": "browser-descriptor",
               "before_sha256": hashlib.sha256(before).hexdigest(), "after_sha256": hashlib.sha256(after).hexdigest(),
               "reference": "https://github.com/WhiskeySockets/Baileys/issues/2671"}
    hashes = {path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(destination.rglob("*")) if path.is_file()}
    manifest = {"schema": "savia-whatsapp-local-package/v1", "rc_revision": RC_REVISION,
                "whatsapp_mcp_revision": MCP_REVISION, "files": hashes,
                "feature_revision": git(ROOT, "rev-parse", "HEAD").decode().strip(),
                "mcp_overlays": [overlay],
                "real_bank_actions": False, "state_included": False, "secrets_included": False}
    (destination / "standalone-package.json").write_text(json.dumps(manifest, indent=2))
    archive = destination.with_suffix(".zip")
    if archive.exists():
        raise ValueError("Package archive already exists")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                output.write(path, path.relative_to(destination))
    print(json.dumps({"package": str(archive), "files": len(hashes),
                      "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}))
