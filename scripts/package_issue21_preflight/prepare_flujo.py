"""Create a public pinned FLUJO build context; never copy local data or Git config."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath

PIN = "51ff39fc5bac84cbbb49bbd2b21b5ab89de8b14b"
TREE = "b754c1cae7def51ab9a1343c1726a63c30d2c53a"
CHECKPOINT = "banking-package-issue21/v2"
ROOT_FILES = frozenset({
    "Dockerfile", ".dockerignore", "package.json", "package-lock.json", "next.config.mjs",
    "next-env.d.ts", "tsconfig.json", "tsconfig.build.json", "postcss.config.mjs",
    "eslint.config.mjs", "LICENSE",
})
PREFIXES = ("src/", "scripts/", "mcp-servers/", "public/", "bin/")


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def prepare(repo: Path, out: Path, manifest: Path) -> dict:
    if git(repo, "rev-parse", "HEAD").decode().strip() != PIN:
        raise ValueError("FLUJO checkout must match the fixed reviewed commit")
    if git(repo, "rev-parse", f"{PIN}^{{tree}}").decode().strip() != TREE:
        raise ValueError("FLUJO tree mismatch")
    if out.exists():
        raise ValueError("Context output must be a new directory")
    entries = []
    for line in git(repo, "ls-tree", "-r", PIN).decode().splitlines():
        meta, name = line.split("\t", 1)
        if name not in ROOT_FILES and not name.startswith(PREFIXES):
            continue
        mode, kind, oid = meta.split()
        parts = PurePosixPath(name).parts
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError(f"Unreviewed non-file source entry: {name}")
        if any(part in {".git", "node_modules", ".next", "private"} or part.startswith(".env") for part in parts):
            raise ValueError(f"Forbidden context entry: {name}")
        if PurePosixPath(name).suffix.lower() in {".pdf", ".parquet", ".duckdb", ".sqlite", ".zip", ".pem", ".key"}:
            raise ValueError(f"Forbidden data/credential context entry: {name}")
        data = git(repo, "cat-file", "blob", oid)
        target = out.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if mode == "100755" else 0o644)
        entries.append({"path": name, "gitOid": oid, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    if not ROOT_FILES.issubset({entry["path"] for entry in entries}):
        raise ValueError("Required FLUJO root source files missing")
    version = json.loads((out / "package.json").read_text(encoding="utf-8"))["version"]
    if version != "3.46.1":
        raise ValueError("Pinned application version mismatch")
    receipt = {"schema": "flujo-package-source-context/v2", "schema_version": 2,
        "checkpoint": CHECKPOINT, "sourceRevision": PIN,
        "sourceTree": TREE, "applicationVersion": version,
        "source": "exact pinned Git blobs; explicit runtime/build closure",
        "rootFiles": sorted(ROOT_FILES), "prefixes": list(PREFIXES),
        "files": entries, "runtimeExecution": False}
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.repo.resolve(), args.out.resolve(), args.manifest.resolve())
    print(json.dumps({"sourceRevision": result["sourceRevision"], "files": len(result["files"]), "runtimeExecution": False}))
