"""Remote disposable-container packaging proof; generated fiction and discovery only.

This script deliberately has no tool invocation, provider request, registration,
HTTP listener, assertion signing, or live source configuration. Its runtime imports
and MCP stdio child are gated to GitHub Actions. Pure helpers can be tested locally.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import importlib.metadata
import io
import json
import os
import platform
import re
import sqlite3
import sys
import tempfile
from pathlib import Path, PurePosixPath


PINNED_BANK_SOURCE = "529bcca2ae83a705e8c372a065602f3e27fa11da"
READ_TOOLS = frozenset({"banking_status", "list_my_transactions", "get_my_transaction"})
HOST_ACTION_TOOLS = frozenset({
    "prepare_unrecognized_charge", "confirm_simulated_intake", "read_intake_receipt",
    "create_verified_handoff", "read_verified_handoff",
})
WRITE_HINT_TOOLS = frozenset({
    "prepare_unrecognized_charge", "confirm_simulated_intake", "create_verified_handoff",
})
EMPTY_STATE_TABLES = (
    "replays", "revoked", "sessions", "capabilities", "action_pending",
    "sandbox_cases", "sandbox_handoffs", "sandbox_coverage",
)
IMPORTED_PACKAGES = ("banking_mcp", "pipeline")
UNPROVEN = [
    "customer_acceptance", "model_or_provider_acceptance", "delegated_auth_acceptance",
    "joined_runtime_acceptance", "host_action_execution", "live_s3_verification",
]


class PreflightError(Exception):
    """A static failure code safe to publish without an exception's raw contents."""


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def value_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def context_tree_sha256(root: Path, paths: list[str]) -> str:
    """Match the context receipt's name/size/content digest over verified files."""
    digest = hashlib.sha256()
    for relative in sorted(paths):
        content = (root / safe_relative_path(relative)).read_bytes()
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(str(len(content)).encode("ascii") + b"\0")
        digest.update(content)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def require_remote_ci() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true" or platform.system() != "Linux":
        raise PreflightError("remote_github_actions_linux_required")


def safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PreflightError("invalid_manifest_path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise PreflightError("invalid_manifest_path")
    return value


def installed_source_inventory(root: Path) -> list[dict]:
    """The package source tree, including contracts and recursive requirements."""
    paths = []
    for package in IMPORTED_PACKAGES:
        package_root = root / package
        if not package_root.is_dir() or package_root.is_symlink():
            raise PreflightError("installed_package_directory_missing")
        for path in package_root.rglob("*"):
            if path.is_symlink():
                raise PreflightError("installed_source_symlink")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                paths.append(path)
    paths.extend(root.glob("requirements*.txt"))
    if any(path.is_symlink() for path in paths):
        raise PreflightError("installed_source_symlink")
    return [{"path": path.relative_to(root).as_posix(), "sha256": file_sha256(path)}
            for path in sorted(paths)]


def validate_source_manifest(manifest: dict, installed: list[dict], expected_revision: str) -> dict:
    if (expected_revision != PINNED_BANK_SOURCE or manifest.get("schema_version") != 1
            or manifest.get("proof_kind") != "source-context"
            or manifest.get("bank_source_revision") != expected_revision
            or not re.fullmatch(r"[a-f0-9]{40}", manifest.get("candidate_ci_head", ""))):
        raise PreflightError("source_revision_or_manifest_mismatch")
    files = manifest.get("runtime_files")
    if not isinstance(files, list) or not files:
        raise PreflightError("manifest_runtime_files_missing")
    expected = {}
    for item in files:
        if not isinstance(item, dict):
            raise PreflightError("manifest_runtime_file_invalid")
        relative = safe_relative_path(item.get("path"))
        if (relative in expected or item.get("source_revision") != expected_revision
                or not re.fullmatch(r"[a-f0-9]{64}", item.get("sha256", ""))):
            raise PreflightError("manifest_runtime_file_invalid")
        expected[relative] = item["sha256"]
    actual = {item["path"]: item["sha256"] for item in installed}
    if len(actual) != len(installed) or actual != expected:
        raise PreflightError("installed_source_bytes_mismatch")
    drift = manifest.get("core_drift_check", {})
    if (drift.get("status") != "unchanged"
            or drift.get("compared_revision") != manifest["candidate_ci_head"]
            or set(drift.get("paths", [])) != set(expected)):
        raise PreflightError("candidate_runtime_source_drift")
    requirements = manifest.get("requirements", {})
    if requirements.get("entrypoint") != "requirements-mcp.txt":
        raise PreflightError("requirements_entrypoint_mismatch")
    requirement_files = sorted(path for path in expected if path.startswith("requirements") and path.endswith(".txt"))
    if set(requirement_files) != {"requirements-mcp.txt", "requirements-pipeline.txt", "requirements-s3.txt"}:
        raise PreflightError("recursive_requirements_missing")
    if (set(requirements.get("files", [])) != set(requirement_files)
            or not re.fullmatch(r"[a-f0-9]{64}", requirements.get("aggregate_sha256", ""))
            or not re.fullmatch(r"[a-f0-9]{64}", manifest.get("runtime_tree_sha256", ""))):
        raise PreflightError("source_context_aggregate_metadata_invalid")
    return {"bank_source_revision": expected_revision,
            "candidate_ci_head": manifest["candidate_ci_head"],
            "installed_source_tree_sha256": value_sha256(installed),
            "source_context_runtime_tree_sha256": manifest.get("runtime_tree_sha256"),
            "requirements_aggregate_sha256": requirements["aggregate_sha256"],
            "requirements": [{"path": path, "sha256": expected[path]} for path in requirement_files]}


def verify_context_aggregate_hashes(root: Path, manifest: dict, installed: list[dict]) -> None:
    if (context_tree_sha256(root, [item["path"] for item in installed]) != manifest["runtime_tree_sha256"]
            or context_tree_sha256(root, manifest["requirements"]["files"])
            != manifest["requirements"]["aggregate_sha256"]):
        raise PreflightError("source_context_aggregate_bytes_mismatch")


def verify_driver_source(manifest: dict, driver: Path) -> dict:
    matches = [item for item in manifest.get("packaging_files", [])
               if item.get("path") == "scripts/package_preflight/verify_installed.py"]
    if (len(matches) != 1 or matches[0].get("sha256") != file_sha256(driver)
            or matches[0].get("source_revision") != manifest["candidate_ci_head"]):
        raise PreflightError("candidate_verifier_source_mismatch")
    return {"path": "scripts/package_preflight/verify_installed.py", "sha256": matches[0]["sha256"],
            "source_revision": matches[0]["source_revision"]}


def validate_tool_inventory(tools: list[dict], expected_schemas: dict) -> list[dict]:
    names = [tool.get("name") for tool in tools]
    expected_names = READ_TOOLS | HOST_ACTION_TOOLS
    if len(names) != 8 or len(set(names)) != 8 or set(names) != expected_names:
        raise PreflightError("advertised_tool_inventory_mismatch")
    for tool in tools:
        name = tool["name"]
        if tool.get("inputSchema") != expected_schemas[name]:
            raise PreflightError("advertised_input_schema_mismatch")
        annotations = tool.get("annotations", {})
        if (annotations.get("readOnlyHint") != (name not in WRITE_HINT_TOOLS)
                or annotations.get("destructiveHint") is not False
                or annotations.get("idempotentHint") is not True
                or annotations.get("openWorldHint") is not False):
            raise PreflightError("advertised_tool_annotation_mismatch")
    return sorted(tools, key=lambda tool: tool["name"])


def dependencies_inventory() -> list[dict]:
    rows = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if not name:
            raise PreflightError("installed_distribution_name_missing")
        record = distribution.read_text("RECORD")
        rows.append({"name": re.sub(r"[-_.]+", "-", name).lower(), "version": distribution.version,
                     "installed_record_sha256": hashlib.sha256(record.encode()).hexdigest() if record else None})
    rows.sort(key=lambda row: (row["name"], row["version"]))
    if len({row["name"] for row in rows}) != len(rows):
        raise PreflightError("duplicate_installed_distribution")
    versions = {row["name"]: row["version"] for row in rows}
    for name, version in {"duckdb": "1.5.5", "mcp": "1.30.0", "pyjwt": "2.15.0", "rfc8785": "0.1.4"}.items():
        if versions.get(name) != version:
            raise PreflightError("pinned_dependency_version_mismatch")
    for name in ("anyio", "boto3", "cryptography", "pydantic", "pyyaml", "starlette"):
        if name not in versions:
            raise PreflightError("required_dependency_missing")
    return rows


def imports_inventory(root: Path, installed: list[dict]) -> list[dict]:
    expected = {item["path"]: item["sha256"] for item in installed}
    imported = []
    for name, module in sorted(sys.modules.items()):
        if not any(name == package or name.startswith(package + ".") for package in IMPORTED_PACKAGES):
            continue
        location = getattr(module, "__file__", None)
        if not location:
            raise PreflightError("installed_import_file_missing")
        path = Path(location).resolve()
        if not path.is_relative_to(root):
            raise PreflightError("imported_checkout_or_external_package")
        relative = path.relative_to(root).as_posix()
        digest = file_sha256(path)
        if expected.get(relative) != digest:
            raise PreflightError("installed_import_bytes_mismatch")
        imported.append({"module": name, "path": str(path), "sha256": digest})
    required = {"banking_mcp", "banking_mcp.config", "banking_mcp.service", "banking_mcp.server",
                "pipeline", "pipeline.fixture", "pipeline.__main__"}
    if not required.issubset({item["module"] for item in imported}):
        raise PreflightError("required_installed_import_missing")
    return imported


def empty_state_receipt(state_db: Path) -> dict:
    if not state_db.is_file():
        raise PreflightError("discovery_state_database_missing")
    with sqlite3.connect(state_db.as_uri() + "?mode=ro", uri=True) as connection:
        counts = {table: connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                  for table in EMPTY_STATE_TABLES}
        identity_count = connection.execute("SELECT count(*) FROM sandbox_ledger_identity").fetchone()[0]
    if any(counts.values()) or identity_count != 1:
        raise PreflightError("discovery_created_action_or_authority_state")
    return {"empty_table_row_counts": counts, "bootstrap_ledger_identity_rows": identity_count,
            "tool_calls": 0, "action_writes": 0}


def fixture_snapshot_receipt(out: Path) -> dict:
    build_id = (out / "CURRENT").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", build_id):
        raise PreflightError("generated_snapshot_pointer_invalid")
    build = out / "builds" / build_id
    manifest = json.loads((build / "snapshot.json").read_text(encoding="utf-8"))
    if (manifest.get("build_id") != build_id or not manifest.get("gold_files")
            or not re.fullmatch(r"[a-f0-9]{16}", manifest.get("source_fingerprint", ""))):
        raise PreflightError("generated_snapshot_manifest_invalid")
    gold_files = []
    for relative, size in sorted(manifest["gold_files"].items()):
        path = build / "gold" / safe_relative_path(relative)
        if not path.is_file() or path.stat().st_size != size:
            raise PreflightError("generated_gold_inventory_mismatch")
        gold_files.append({"path": relative, "bytes": size, "sha256": file_sha256(path)})
    return {"synthetic": True, "generator": "pipeline.fixture.write_base",
            "organizer_data_used": False, "source_fingerprint": manifest["source_fingerprint"],
            "snapshot_manifest_sha256": file_sha256(build / "snapshot.json"),
            "gold_inventory_sha256": value_sha256(gold_files), "gold_file_count": len(gold_files)}


def generated_discovery(root: Path, temporary: Path) -> tuple[dict, list[dict], dict]:
    """Run only within remote CI after the installed bytes pass the manifest check."""
    import anyio
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from banking_mcp.config import Config
    from banking_mcp.service import SCHEMAS
    from pipeline.__main__ import main as run_pipeline
    from pipeline.fixture import cid, write_base

    # Import transport code from the installed copy without constructing a service.
    importlib.import_module("banking_mcp.server")
    source, out, reports = temporary / "generated-source", temporary / "out", temporary / "reports"
    write_base(source)
    generated_files = [{"path": path.relative_to(source).as_posix(), "sha256": file_sha256(path)}
                       for path in sorted(source.rglob("*.csv"))]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        code = run_pipeline(["run", "--source", str(source), "--out", str(out),
                             "--reports", str(reports), "--threads", "2", "--memory-limit", "1GB"])
    if code != 0:
        raise PreflightError("generated_fixture_pipeline_failed")
    fixture = fixture_snapshot_receipt(out)
    fixture["generated_source_inventory_sha256"] = value_sha256(generated_files)
    fixture["generated_source_file_count"] = len(generated_files)
    # Only delegated mode advertises host actions. This ephemeral public key and
    # fictional mapping satisfy the real config; no assertion or key is persisted.
    public_pem = Ed25519PrivateKey.generate().public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    state_db, config_path = temporary / "state.db", temporary / "generated-config.json"
    config = Config(mode="delegated", data_dir=out, state_db=state_db,
                    service_token="generated-discovery-only-" + os.urandom(32).hex(),
                    public_keys={"generated-discovery": public_pem},
                    principal_customers={"generated-discovery-subject": cid(6)})
    config_path.write_text(config.model_dump_json(), encoding="utf-8")
    config_path.chmod(0o600)
    expected_schemas = {name: model.model_json_schema() for name, model in SCHEMAS.items()}
    (temporary / "home").mkdir()
    child_env = {"HOME": str(temporary / "home"), "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
                 "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}

    async def discover() -> tuple[dict, list[dict]]:
        with anyio.fail_after(60):
            parameters = StdioServerParameters(command=sys.executable,
                args=["-m", "banking_mcp", "serve", "--config", str(config_path), "--transport", "stdio"],
                cwd=str(root), env=child_env)
            with (temporary / "discovery-stderr.log").open("w", encoding="utf-8") as errors:
                async with stdio_client(parameters, errlog=errors) as (read, write):
                    async with ClientSession(read, write) as client:
                        initialized = await client.initialize()
                        result = await client.list_tools()
                        if result.nextCursor is not None:
                            raise PreflightError("unexpected_tool_inventory_pagination")
                        tools = [tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in result.tools]
                        server_info = initialized.serverInfo.model_dump(mode="json", exclude_none=True)
                        if (server_info.get("name") != "banking-mcp"
                                or server_info.get("version") != importlib.import_module("banking_mcp").__version__):
                            raise PreflightError("installed_stdio_server_identity_mismatch")
                        return {"server_info": server_info, "protocol_version": initialized.protocolVersion,
                                "capabilities": initialized.capabilities.model_dump(mode="json", by_alias=True, exclude_none=True),
                                "transport": "stdio", "requests": ["initialize", "tools/list"],
                                "mode": "delegated", "generated_fixture_only": True,
                                "source_env_configured": False, "assertions_created": 0}, validate_tool_inventory(tools, expected_schemas)

    discovery, tools = anyio.run(discover)
    return {"fixture": fixture, "discovery": discovery}, tools, empty_state_receipt(state_db)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--banking-root", type=Path, default=Path("/opt/banking-mcp"))
    parser.add_argument("--receipt-dir", type=Path, required=True)
    parser.add_argument("--expected-source-revision", required=True)
    parser.add_argument("--source-manifest", type=Path,
                        default=Path(__file__).resolve().with_name("source-context-manifest.json"))
    args = parser.parse_args(argv)
    receipt = {"schema_version": 1, "proof_kind": "remote-installed-package-discovery",
               "status": "failed", "unproven": UNPROVEN}
    stage = "remote_ci_guard"
    try:
        require_remote_ci()
        root = args.banking_root.resolve(strict=True)
        receipt_dir = args.receipt_dir.resolve()
        if receipt_dir == root or receipt_dir.is_relative_to(root):
            raise PreflightError("receipt_directory_inside_installed_source")
        receipt_dir.mkdir(parents=True, exist_ok=True)
        stage = "installed_source"
        manifest = json.loads(args.source_manifest.read_text(encoding="utf-8"))
        installed = installed_source_inventory(root)
        receipt["source"] = validate_source_manifest(manifest, installed, args.expected_source_revision)
        verify_context_aggregate_hashes(root, manifest, installed)
        receipt["source"]["source_context_manifest_sha256"] = file_sha256(args.source_manifest)
        receipt["verifier"] = verify_driver_source(manifest, Path(__file__).resolve())
        write_json(receipt_dir / "installed-source-inventory.json", installed)
        stage = "installed_dependencies"
        dependencies = dependencies_inventory()
        write_json(receipt_dir / "installed-dependencies.json", dependencies)
        receipt["dependency_inventory_sha256"] = value_sha256(dependencies)
        receipt["python"] = {"version": platform.python_version(), "executable": sys.executable}
        # The image copies source into this location, as the actual worker does.
        # Each subsequently imported module must resolve to these verified bytes.
        sys.path.insert(0, str(root))
        stage = "generated_fixture_and_stdio_discovery"
        with tempfile.TemporaryDirectory(prefix="generated-bank-package-") as workspace:
            evidence, tools, state = generated_discovery(root, Path(workspace).resolve())
        receipt.update(evidence)
        receipt["state"] = state
        write_json(receipt_dir / "tool-inventory.json", {"read_tools": sorted(READ_TOOLS),
                   "host_action_tools": sorted(HOST_ACTION_TOOLS), "tools": tools})
        receipt["tool_inventory_sha256"] = value_sha256(tools)
        stage = "installed_import_paths"
        imports = imports_inventory(root, installed)
        write_json(receipt_dir / "installed-imports.json", imports)
        receipt["installed_imports_sha256"] = value_sha256(imports)
        receipt["artifacts"] = [{"path": path.name, "bytes": path.stat().st_size, "sha256": file_sha256(path)}
                                for path in sorted(receipt_dir.glob("*.json")) if path.name != "receipt.json"]
        receipt["status"] = "passed"
        write_json(receipt_dir / "receipt.json", receipt)
        print("Remote installed-package import and stdio inventory proof passed (3 reads, 5 host actions, 0 calls).")
        return 0
    except Exception as error:
        receipt["failure"] = {"stage": stage, "code": str(error) if isinstance(error, PreflightError)
                              else "verification_failed", "exception_type": type(error).__name__}
        # A local refusal must not create files or load the banking/runtime packages.
        if stage != "remote_ci_guard" and args.receipt_dir.exists():
            write_json(args.receipt_dir / "receipt.json", receipt)
        print(f"Installed-package proof failed at {stage}: {receipt['failure']['code']}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
