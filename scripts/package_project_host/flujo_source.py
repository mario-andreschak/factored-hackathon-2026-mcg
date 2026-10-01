"""Read a fixed stock FLUJO source closure without importing or executing it.

This successor does not reuse banking-adapter package receipts. Collecting
source is not a build, deployment, provider test or native-process isolation
proof. Banking code and authority belong to the separate project source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
from typing import Callable


PIN = "3fccc557df97aba0e96ce28a8e6eebaa8e71d7d9"
TREE = "780c2cf42266f8e55ff1917c137b196ee97df959"
VERSION = "3.46.1"
ROOT_FILES = frozenset({
    "Dockerfile", ".dockerignore", "package.json", "package-lock.json", "next.config.mjs",
    "next-env.d.ts", "tsconfig.json", "tsconfig.build.json", "postcss.config.mjs",
    "eslint.config.mjs", "LICENSE",
})
PREFIXES = ("src/", "scripts/", "mcp-servers/", "public/", "bin/")
DOMAIN_PREFIXES = (
    "src/app/v1/banking/", "src/backend/services/banking/",
    "src/integrations/hackathon-banking/",
)
FORBIDDEN_SUFFIXES = frozenset({
    ".pdf", ".parquet", ".duckdb", ".sqlite", ".sqlite3", ".zip", ".pem", ".key",
})
GitReader = Callable[..., bytes]


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def collect(repo: Path, *, read: GitReader = git) -> tuple[dict[str, bytes], dict]:
    """Return validated Git blobs and hashes; never read dirty working files."""
    if read(repo, "rev-parse", "HEAD").decode().strip() != PIN:
        raise ValueError("FLUJO checkout must match the fixed restored commit")
    if read(repo, "rev-parse", f"{PIN}^{{tree}}").decode().strip() != TREE:
        raise ValueError("FLUJO source tree mismatch")
    files: dict[str, bytes] = {}
    records = []
    for line in read(repo, "ls-tree", "-r", PIN).decode().splitlines():
        meta, name = line.split("\t", 1)
        if name.startswith(DOMAIN_PREFIXES):
            raise ValueError("Banking domain code cannot enter stock FLUJO")
        if name not in ROOT_FILES and not name.startswith(PREFIXES):
            continue
        path = PurePosixPath(name)
        if (path.is_absolute() or path.as_posix() != name or "\\" in name
                or any(part in {"..", ".git", "node_modules", ".next", "private"}
                       or part.startswith(".env") for part in path.parts)
                or path.suffix.lower() in FORBIDDEN_SUFFIXES):
            raise ValueError("Forbidden data, credential or noncanonical source path")
        mode, kind, oid = meta.split()
        if mode not in {"100644", "100755"} or kind != "blob" or name in files:
            raise ValueError("Unreviewed non-file or duplicate source entry")
        data = read(repo, "cat-file", "blob", oid)
        files[name] = data
        records.append({"path": name, "gitOid": oid, "mode": mode,
                        "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    if not ROOT_FILES.issubset(files):
        raise ValueError("Required stock FLUJO build inputs missing")
    if json.loads(files["package.json"])["version"] != VERSION:
        raise ValueError("FLUJO application version mismatch")
    manifest = {
        "schema": "project-host-stock-flujo-source/v1",
        "sourceRevision": PIN, "sourceTree": TREE, "applicationVersion": VERSION,
        "source": "Exact restored Git blobs; no working-tree inputs",
        "rootFiles": sorted(ROOT_FILES), "prefixes": list(PREFIXES), "files": records,
        "preparationOnly": True, "runtimeExecution": False,
        "nativeIsolationProven": False, "imageBuilt": False,
        "scope": "Source closure only; no banking adapter, runtime or capacity evidence",
    }
    return files, manifest


def prepare(repo: Path, out: Path, manifest_path: Path) -> dict:
    """Validate the entire closure before materializing a new source directory."""
    out, manifest_path = out.resolve(), manifest_path.resolve()
    if (out == manifest_path or out in manifest_path.parents
            or manifest_path in out.parents):
        raise ValueError("Manifest and source directory must not overlap")
    if out.exists() or manifest_path.exists():
        raise ValueError("Source outputs must be new paths")
    files, manifest = collect(repo)
    out.mkdir(parents=True)
    modes = {entry["path"]: entry["mode"] for entry in manifest["files"]}
    for name, data in files.items():
        target = out.joinpath(*PurePosixPath(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if modes[name] == "100755" else 0o644)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.repo.resolve(), args.out.resolve(), args.manifest.resolve())
    print(json.dumps({"sourceRevision": result["sourceRevision"],
                      "files": len(result["files"]), "runtimeExecution": False}))
