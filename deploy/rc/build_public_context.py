"""Export an allowlisted immutable Git tree, never a working-tree overlay."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PREFIXES = ("banking_mcp/", "dispute_workflow/", "savia_assistant/", "pipeline/", "resources/", "config/",
            "frontend/server/", "frontend/src/", "frontend/public/", "avatar/server/", "avatar/src/", "avatar/public/", "deploy/rc/", "contracts/")
FILES = {"requirements-dispute.txt", "requirements-pipeline.txt", "requirements-s3.txt", "frontend/requirements.txt",
         "scripts/qualify_dispute_app.py", "scripts/run_dispute.py", "scripts/native_dispute_qualification.py",
         "scripts/native_dispute_qualification.ts", "scripts/native_dispute_qualification.mjs"}
for component in ("frontend", "avatar"):
    FILES.update(f"{component}/{name}" for name in ("package.json", "package-lock.json", "index.html", "vite.config.ts", "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json"))


def export(destination, revision):
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("fresh empty build context required")
    destination.mkdir(parents=True, exist_ok=True)
    git = lambda *args: subprocess.check_output(["git", "-C", str(ROOT), *args])
    head = git("rev-parse", revision).decode().strip()
    tree = git("rev-parse", head + "^{tree}").decode().strip()
    hashes = {}
    for entry in git("ls-tree", "-r", "-z", head).split(b"\0"):
        if not entry:
            continue
        metadata, raw = entry.split(b"\t", 1)
        name = raw.decode()
        if not (name in FILES or name.startswith(PREFIXES)):
            continue
        path = Path(name)
        if metadata.split()[0] != b"100644" and metadata.split()[0] != b"100755":
            raise ValueError("nonregular build source denied")
        if (path.suffix.lower() in {".env", ".csv", ".sqlite", ".sqlite3", ".pem", ".key"}
                or any(part in {"private", ".overlay", "node_modules", "dist", "__pycache__"} for part in path.parts)
                or "openrouter.env" in name):
            raise ValueError("private or generated file in build allowlist")
        payload = git("show", f"{head}:{name}")
        output = destination / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
    manifest = {"schema": "savia-public-rc-source/v1", "git_head": head, "git_tree": tree, "files": hashes,
                "fiction_only": True, "flujo_built": False,
                "flujo_compatibility_reference": "0ba62296520a505e6d71eddf5aa650691f3dc311"}
    (destination / "source-manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"git_head": head, "files": len(hashes), "context": str(destination)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args()
    export(args.destination, args.revision)
