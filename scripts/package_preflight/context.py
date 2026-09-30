"""Build a minimal, provenance-bearing Docker context without reading runtime data.

Only the audited import closure below is exported from the pinned banking commit.
Candidate packaging probes are exported separately from Git HEAD. This receipt is
source evidence; installed dependency and command checks belong to remote CI.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import tempfile
from typing import Mapping


PINNED_BANK_SOURCE = "529bcca2ae83a705e8c372a065602f3e27fa11da"

# Explicitly audited: banking_mcp.__main__ -> service/repository/security/actions
# and its lazy server import. repository imports pipeline.common. The synthetic
# fixture and pipeline CLI add the second import closure. No directory COPY.
RUNTIME_PYTHON_FILES = (
    "banking_mcp/__init__.py",
    "banking_mcp/__main__.py",
    "banking_mcp/actions.py",
    "banking_mcp/config.py",
    "banking_mcp/repository.py",
    "banking_mcp/security.py",
    "banking_mcp/server.py",
    "banking_mcp/service.py",
    "pipeline/__init__.py",
    "pipeline/__main__.py",
    "pipeline/bronze.py",
    "pipeline/common.py",
    "pipeline/fixture.py",
    "pipeline/gold.py",
    "pipeline/lookup.py",
    "pipeline/report.py",
    "pipeline/silver.py",
    "pipeline/verify.py",
    "pipeline/writer.py",
)
# pipeline.common.load_contracts() reads this resource beside its own module.
RUNTIME_RESOURCES = ("pipeline/contracts.yaml",)
# requirements-mcp.txt includes the other two files. Preserve their exact bytes.
REQUIREMENT_FILES = (
    "requirements-mcp.txt",
    "requirements-pipeline.txt",
    "requirements-s3.txt",
)
RUNTIME_FILES = tuple(sorted((*RUNTIME_PYTHON_FILES, *RUNTIME_RESOURCES, *REQUIREMENT_FILES)))
PACKAGING_FILES = (
    "scripts/package_preflight/context.py",
    "scripts/package_preflight/verify_flujo.cjs",
    "scripts/package_preflight/verify_installed.py",
)
ENTRYPOINTS = ("banking_mcp.__main__", "pipeline.__main__")
LOCAL_PACKAGES = frozenset({"banking_mcp", "pipeline"})


class ContextError(RuntimeError):
    """A context cannot prove the required source identity or minimal closure."""


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise ContextError(f"git {args[0]} failed: {result.stderr.decode('utf-8', errors='replace').strip()}")
    return result.stdout


def resolve_commit(repo: Path, revision: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}").decode("ascii").strip()


def read_tree(repo: Path, revision: str) -> dict[str, tuple[str, str]]:
    result = {}
    for record in git(repo, "ls-tree", "-r", "-z", "--full-tree", revision).split(b"\0"):
        if not record:
            continue
        metadata, path = record.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        if kind == "blob":
            result[path.decode("utf-8")] = (mode, oid)
    return result


def read_blobs(repo: Path, tree: Mapping[str, tuple[str, str]], paths: tuple[str, ...]) -> dict[str, bytes]:
    result = {}
    for path in paths:
        if path not in tree:
            raise ContextError(f"required committed file missing: {path}")
        mode, oid = tree[path]
        if mode not in {"100644", "100755"}:
            raise ContextError(f"required file must be a regular Git blob: {path} ({mode})")
        result[path] = git(repo, "cat-file", "blob", oid)
    return result


def content_digest(files: Mapping[str, bytes]) -> str:
    """Hash sorted relative names and exact bytes with unambiguous separators."""
    digest = hashlib.sha256()
    for path, content in sorted(files.items()):
        digest.update(path.encode("utf-8") + b"\0")
        digest.update(str(len(content)).encode("ascii") + b"\0")
        digest.update(content)
    return digest.hexdigest()


def _module(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def audit_import_closure(files: Mapping[str, bytes], available_paths: set[str]) -> list[str]:
    """Resolve local static imports, including imports inside CLI functions.

    This does not import or execute banking code. Unknown local imports fail
    closed; the reviewed whitelist cannot silently expand with a directory copy.
    """
    modules = {_module(path): path for path in available_paths if path.endswith(".py")
               and path.split("/", 1)[0] in LOCAL_PACKAGES}
    included: set[str] = set()
    pending = list(ENTRYPOINTS)

    def include(name: str) -> None:
        if name.split(".", 1)[0] not in LOCAL_PACKAGES:
            return
        if name not in modules:
            raise ContextError(f"unresolved local import: {name}")
        for index in range(1, len(name.split(".")) + 1):
            ancestor = ".".join(name.split(".")[:index])
            if ancestor in modules and ancestor not in included:
                pending.append(ancestor)

    while pending:
        name = pending.pop()
        if name in included:
            continue
        path = modules.get(name)
        if path is None or path not in files:
            raise ContextError(f"import outside explicit runtime whitelist: {name}")
        included.add(name)
        include(name)  # Include each package's __init__.py as Python does.
        try:
            tree = ast.parse(files[path].decode("utf-8-sig"), filename=path)
        except (SyntaxError, UnicodeDecodeError) as exc:
            raise ContextError(f"cannot audit Python source {path}: {exc}") from exc
        package = name if path.endswith("/__init__.py") else name.rsplit(".", 1)[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    include(alias.name)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parents = package.split(".")
                    if node.level > len(parents):
                        raise ContextError(f"relative import escapes local package: {path}")
                    base = ".".join([*parents[:len(parents) - node.level + 1], *base.split(".")]).rstrip(".")
                include(base)
                for alias in node.names:
                    child = f"{base}.{alias.name}"
                    if child in modules:
                        include(child)
            elif isinstance(node, ast.Call) and (
                isinstance(node.func, ast.Name) and node.func.id in {"__import__", "import_module"}
                or isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
            ):
                raise ContextError(f"dynamic imports require an explicit source audit: {path}")
    closure = sorted(modules[name] for name in included)
    if set(closure) != set(files).intersection(available_paths):
        unused = sorted(set(files).intersection(available_paths) - set(closure))
        raise ContextError(f"runtime whitelist contains files outside audited import closure: {unused}")
    return closure


def audit_requirements(files: Mapping[str, bytes]) -> list[str]:
    visited: set[str] = set()
    pending = ["requirements-mcp.txt"]
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        if path not in files or path not in REQUIREMENT_FILES:
            raise ContextError(f"requirements include outside whitelist: {path}")
        visited.add(path)
        for line in files[path].decode("utf-8-sig").splitlines():
            tokens = shlex.split(line, comments=True)
            if not tokens:
                continue
            if tokens[0] in {"-r", "--requirement", "-c", "--constraint"}:
                if len(tokens) != 2:
                    raise ContextError(f"invalid requirements include in {path}")
                target = tokens[1]
            elif tokens[0].startswith(("-r", "-c", "--requirement=", "--constraint=")):
                target = tokens[0].split("=", 1)[1] if "=" in tokens[0] else tokens[0][2:]
                if len(tokens) != 1:
                    raise ContextError(f"invalid requirements include in {path}")
            else:
                continue
            target_path = PurePosixPath(target)
            if target_path.is_absolute() or ".." in target_path.parts or "\\" in target or ":" in target:
                raise ContextError(f"unsafe requirements include in {path}: {target}")
            pending.append((PurePosixPath(path).parent / target_path).as_posix())
    if visited != set(REQUIREMENT_FILES):
        raise ContextError("requirements whitelist differs from recursive pinned requirements closure")
    return sorted(visited)


def assert_core_unchanged(pinned: Mapping[str, tuple[str, str]], candidate: Mapping[str, tuple[str, str]]) -> None:
    paths = set(RUNTIME_FILES)
    # Also reject new banking Python modules even when no pinned import uses them.
    paths.update(path for path in (*pinned, *candidate)
                 if path.startswith("banking_mcp/") and path.endswith(".py"))
    drift = sorted(path for path in paths if pinned.get(path) != candidate.get(path))
    if drift:
        raise ContextError(f"candidate bank runtime differs from pinned source: {', '.join(drift)}")


def _output_location(repo: Path, output: Path) -> Path:
    output = output.resolve()
    if output.exists():
        raise ContextError("output must not already exist; provide a fresh context directory")
    if output == repo:
        raise ContextError("output cannot be the repository root")
    if output.is_relative_to(repo):
        relative = output.relative_to(repo).as_posix()
        check = subprocess.run(["git", "-C", str(repo), "check-ignore", "--no-index", "--quiet", "--", relative], check=False)
        if check.returncode != 0:
            raise ContextError("output inside checkout must be Git ignored")
    return output


def build_context(repo: Path, output: Path, *, source_revision: str = PINNED_BANK_SOURCE,
                  candidate_head: str | None = None) -> dict:
    repo = Path(git(repo.resolve(), "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
    if source_revision != PINNED_BANK_SOURCE:
        raise ContextError(f"bank source must equal pinned revision {PINNED_BANK_SOURCE}")
    source = resolve_commit(repo, source_revision)
    if source != source_revision:
        raise ContextError("bank source must be an exact full commit identity")
    candidate = resolve_commit(repo, "HEAD")
    if candidate_head is not None and candidate_head != candidate:
        raise ContextError("candidate head argument must equal the checkout's exact Git HEAD")
    pinned_tree = read_tree(repo, source)
    candidate_tree = read_tree(repo, candidate)
    assert_core_unchanged(pinned_tree, candidate_tree)
    runtime = read_blobs(repo, pinned_tree, RUNTIME_FILES)
    packaging = read_blobs(repo, candidate_tree, PACKAGING_FILES)
    python_files = {path: runtime[path] for path in RUNTIME_PYTHON_FILES}
    closure = audit_import_closure(python_files, {path for path in pinned_tree if path.endswith(".py")})
    requirements = audit_requirements({path: runtime[path] for path in REQUIREMENT_FILES})

    def records(files: Mapping[str, bytes], tree: Mapping[str, tuple[str, str]], revision: str,
                prefix: str, packaging_paths: bool = False) -> list[dict]:
        return [{"path": path, "context_path": f"{prefix}/{PurePosixPath(path).name if packaging_paths else path}",
                 "sha256": hashlib.sha256(content).hexdigest(), "git_blob_oid": tree[path][1],
                 "git_mode": tree[path][0], "source_revision": revision}
                for path, content in sorted(files.items())]

    manifest = {
        "schema_version": 1,
        "proof_kind": "source-context",
        "bank_source_revision": source,
        "candidate_ci_head": candidate,
        "runtime_files": records(runtime, pinned_tree, source, "bank-runtime"),
        "packaging_files": records(packaging, candidate_tree, candidate, "packaging", True),
        "runtime_tree_sha256": content_digest(runtime),
        "requirements": {"entrypoint": "requirements-mcp.txt", "files": requirements,
                         "aggregate_sha256": content_digest({path: runtime[path] for path in requirements})},
        "core_drift_check": {"compared_revision": candidate, "status": "unchanged", "paths": list(RUNTIME_FILES)},
        "static_import_audit": {"entrypoints": list(ENTRYPOINTS), "python_files": closure},
        "runtime_execution": False,
        "evidence_scope": "Exact exported source identity and static local imports; installed dependencies and runtime imports require the remote package inventory receipt.",
    }
    output = _output_location(repo, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".bank-context-", dir=output.parent))
    try:
        for record in (*manifest["runtime_files"], *manifest["packaging_files"]):
            target = staging / record["context_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            contents = runtime if record["context_path"].startswith("bank-runtime/") else packaging
            target.write_bytes(contents[record["path"]])
            target.chmod(int(record["git_mode"][-3:], 8))
        (staging / "source-context-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.rename(staging, output)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True, help="fresh directory outside checkout or in a Git ignored location")
    parser.add_argument("--source-revision", default=PINNED_BANK_SOURCE)
    parser.add_argument("--candidate-head", help="optional exact expected checkout Git HEAD")
    args = parser.parse_args(argv)
    try:
        manifest = build_context(args.repo, args.output, source_revision=args.source_revision,
                                 candidate_head=args.candidate_head)
    except (ContextError, OSError) as exc:
        parser.exit(1, f"source context rejected: {exc}\n")
    print(json.dumps({"manifest": str(args.output.resolve() / "source-context-manifest.json"),
                      "bank_source_revision": manifest["bank_source_revision"],
                      "candidate_ci_head": manifest["candidate_ci_head"],
                      "runtime_files": len(manifest["runtime_files"]),
                      "requirements_sha256": manifest["requirements"]["aggregate_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
