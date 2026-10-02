"""Offline, explicit adoption of a retained synthetic dispute ledger.

This module never starts a bank Service or an old worker. An operator must first
retire and settle the old authority and supply protected, independently reviewed
evidence. Missing or changed evidence closes the transition.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import sqlite3
import stat
import tempfile
import time
from urllib.parse import quote

SCHEMA = "dispute-retained-transition/v1"
EVIDENCE_SCHEMA = "dispute-retained-operator-evidence/v1"
LEGACY_COLUMNS = {
    "replays": ("jti", "expires"),
    "revoked": ("session",),
    "sessions": ("session", "subject", "customer"),
    "capabilities": ("id", "kind", "binding", "expires", "payload"),
}
GUARDED_BANK_TABLES = {
    "sessions", "replays", "revoked", "capabilities", "action_pending",
    "sandbox_cases", "sandbox_case_receipts", "sandbox_handoffs",
    "dispute_host_actions", "dispute_host_cancelled", "dispute_handoff_packets",
    "gloria_host_actions", "gloria_host_cancelled", "gloria_handoff_packets",
}
RETAINED_APP_FILES = ("frontend-chat.sqlite3", "dispute-workflow.sqlite3",
                      "gloria-workflow.sqlite3")
SOURCE_DIRS = {
    "banking_mcp": {".py"}, "dispute_workflow": {".py"},
    "frontend/server": {".py"}, "frontend/src": {".ts", ".tsx", ".css"},
    "frontend/public": None, "resources/prompts": {".yml", ".yaml", ".md"},
    "resources/policies": {".md"}, "pipeline": {".py", ".yaml"},
    "config": {".yaml"},
}
SOURCE_FILES = ("scripts/run_dispute.py", "scripts/reconcile_dispute_deployment.py",
                "scripts/native_dispute_qualification.py", "requirements-dispute.txt",
                "resources/dispute_workflow.flow.json", "graph_config_v3.yaml",
                "frontend/package.json", "frontend/package-lock.json",
                "frontend/index.html")
ADDITIVE_SQL = (
    """CREATE TABLE action_pending(
    id TEXT PRIMARY KEY, binding TEXT NOT NULL, customer TEXT NOT NULL,
    transaction_id TEXT NOT NULL, snapshot TEXT NOT NULL, action TEXT NOT NULL,
    decision TEXT NOT NULL, reason TEXT, facts TEXT NOT NULL, expires INTEGER NOT NULL,
    evidence_digest TEXT, request_key TEXT, result_json TEXT, confirmation_state TEXT)""",
    "CREATE UNIQUE INDEX action_pending_request_key ON action_pending(request_key)",
    """CREATE TABLE sandbox_cases(
    id TEXT PRIMARY KEY, customer TEXT NOT NULL, transaction_id TEXT NOT NULL,
    action TEXT NOT NULL, snapshot TEXT NOT NULL, created_at REAL NOT NULL,
    facts TEXT NOT NULL, UNIQUE(customer, transaction_id, action))""",
    "CREATE INDEX sandbox_cases_recent ON sandbox_cases(customer, created_at)",
    "CREATE TABLE sandbox_case_receipts(case_id TEXT PRIMARY KEY, receipt_json TEXT NOT NULL)",
    """CREATE TABLE sandbox_handoffs(
    id TEXT PRIMARY KEY, binding TEXT NOT NULL, customer TEXT NOT NULL,
    transaction_id TEXT, snapshot TEXT, reason TEXT NOT NULL, created_at INTEGER NOT NULL,
    facts TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, packet_json TEXT)""",
    "CREATE TABLE sandbox_ledger_identity(id INTEGER PRIMARY KEY CHECK(id=1), generation TEXT NOT NULL)",
    """CREATE TABLE sandbox_coverage(
    id INTEGER PRIMARY KEY CHECK(id=1), generation TEXT NOT NULL,
    coverage_start INTEGER NOT NULL, provenance_digest TEXT NOT NULL, attested_at INTEGER NOT NULL)""",
    """CREATE TABLE dispute_host_actions(
        binding TEXT NOT NULL, request_id TEXT NOT NULL, query_id TEXT,
        pending_hash TEXT, target TEXT, snapshot TEXT, handoff_id TEXT,
        PRIMARY KEY(binding,request_id))""",
    """CREATE UNIQUE INDEX dispute_host_pending
        ON dispute_host_actions(binding,pending_hash) WHERE pending_hash IS NOT NULL""",
    """CREATE TABLE dispute_host_cancelled(
        binding TEXT NOT NULL, pending_hash TEXT NOT NULL, query_id TEXT,
        cancelled_at INTEGER NOT NULL, PRIMARY KEY(binding,pending_hash))""",
    """CREATE TABLE dispute_handoff_packets(
        binding TEXT NOT NULL, handoff_id TEXT NOT NULL, query_id TEXT,
        request_id TEXT NOT NULL, packet_json TEXT NOT NULL,
        PRIMARY KEY(binding,handoff_id))""",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing protected transition input")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("invalid transition input")
    return value


def _file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing regular proof file")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _source(source_root: Path) -> dict:
    source_root = source_root.resolve(strict=True)
    files = []
    for dirname, suffixes in SOURCE_DIRS.items():
        directory = source_root / dirname
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("missing application source directory")
        files.extend(path for path in directory.rglob("*")
                     if path.is_file() and (suffixes is None or path.suffix in suffixes))
    files.extend(source_root / name for name in SOURCE_FILES)
    manifest = {}
    for path in sorted(files):
        relative = path.relative_to(source_root).as_posix()
        if any(part.startswith(".") for part in path.relative_to(source_root).parts):
            continue
        manifest[relative] = _file_hash(path)
    return {"root": str(source_root), "sha256": _sha(_json(manifest)), "file_count": len(manifest)}


def _connect_ro(path: Path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("retained bank ledger missing")
    db = sqlite3.connect("file:" + quote(str(path.resolve()), safe="/") + "?mode=ro",
                         uri=True, timeout=3)
    db.execute("PRAGMA query_only=ON")
    return db


def _cell(value):
    return {"blob": value.hex()} if isinstance(value, bytes) else value


def _ledger(path: Path, *, legacy: bool) -> dict:
    with contextlib.closing(_connect_ro(path)) as db, db:
        db.execute("BEGIN")
        tables = {name for (name,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if legacy and tables != set(LEGACY_COLUMNS):
            raise ValueError("legacy schema is not the reviewed four-table schema")
        if not set(LEGACY_COLUMNS).issubset(tables):
            raise ValueError("retained ledger tables missing")
        schema = {kind + ":" + name: sql for kind, name, sql in db.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','index') "
            "AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY type,name")}
        rows = {}
        for name, expected in LEGACY_COLUMNS.items():
            columns = tuple(row[1] for row in db.execute("PRAGMA table_info(" + name + ")"))
            if columns != expected:
                raise ValueError("legacy table columns changed")
            hashes = [_sha(_json([_cell(x) for x in row]))
                      for row in db.execute("SELECT * FROM " + name)]
            rows[name] = {"count": len(hashes), "sha256": _sha(_json(sorted(hashes)))}
        generation = None
        coverage = None
        if "sandbox_ledger_identity" in tables:
            found = db.execute("SELECT generation FROM sandbox_ledger_identity WHERE id=1").fetchall()
            if len(found) != 1 or not isinstance(found[0][0], str) or len(found[0][0]) != 64:
                raise ValueError("invalid retained generation")
            generation = found[0][0]
        if "sandbox_coverage" in tables:
            found = db.execute("SELECT generation,coverage_start,provenance_digest FROM sandbox_coverage WHERE id=1").fetchall()
            if len(found) != 1:
                raise ValueError("invalid retained coverage")
            coverage = list(found[0])
        db.rollback()
    return {"schema_sha256": _sha(_json(schema)), "tables": rows,
            "generation": generation, "coverage": coverage}


def _proof_artifact(item: dict, path_key: str, hash_key: str) -> dict:
    path = Path(item.get(path_key, ""))
    expected = item.get(hash_key)
    if not isinstance(expected, str) or re.fullmatch(r"[a-f0-9]{64}", expected) is None:
        raise ValueError("operator proof digest missing")
    if _file_hash(path) != expected:
        raise ValueError("operator proof artifact mismatch")
    return {"path": str(path.resolve()), "sha256": expected}


def _proof(evidence_path: Path, *, bank_path: Path, source: dict, ledger: dict,
           frontend_dir: Path, worker_dir: Path) -> dict:
    evidence = _read_json(evidence_path)
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        raise ValueError("operator evidence schema mismatch")
    if (evidence.get("bank_path") != str(bank_path.resolve())
            or evidence.get("source_sha256") != source["sha256"]
            or evidence.get("legacy_ledger") != ledger):
        raise ValueError("operator evidence does not match retained source and ledger")
    lease = evidence.get("lease", {})
    authority = evidence.get("authority", {})
    if (not isinstance(lease.get("id"), str) or len(lease["id"]) < 16
            or lease.get("exclusive") is not True or lease.get("active") is not True
            or any(authority.get(key) is not True for key in
                   ("old_process_retired", "old_worker_drained", "old_bank_stdio_retired",
                    "late_replies_preserved"))):
        raise ValueError("old authority or exclusive lease unproved")
    lease_artifact = _proof_artifact(lease, "proof_path", "proof_sha256")
    authority_artifact = _proof_artifact(authority, "proof_path", "proof_sha256")
    obligations = evidence.get("obligations")
    if not isinstance(obligations, list) or not obligations or any(
            not isinstance(item, dict) or item.get("state") != "confirmed"
            or not isinstance(item.get("id"), str) or not item["id"] for item in obligations):
        raise ValueError("old obligations unresolved")
    obligation_artifacts = [_proof_artifact(item, "original_receipt_path",
                                             "original_receipt_sha256")
                            for item in obligations]
    archives = evidence.get("archives", {})
    for label, directory in (("frontend", frontend_dir), ("worker", worker_dir)):
        archive = archives.get(label, {})
        if not directory.is_dir() or archive.get("original_dir") != str(directory.resolve()):
            raise ValueError("old state directory not accounted for")
        location = Path(archive.get("path", ""))
        if _file_hash(location) != archive.get("sha256"):
            raise ValueError("sealed old state archive mismatch")
    coverage = evidence.get("coverage", {})
    start, provenance = coverage.get("start"), coverage.get("provenance")
    if (coverage.get("status") != "proved" or type(start) is not int
            or start <= 0 or start > int(time.time()) - 86400
            or not isinstance(provenance, str) or not provenance.startswith("synthetic:")
            or not 16 <= len(provenance) <= 160
            or _file_hash(Path(coverage.get("proof_path", ""))) != coverage.get("proof_sha256")):
        raise ValueError("historical synthetic coverage unproved")
    return {"sha256": _file_hash(evidence_path), "path": str(evidence_path.resolve()),
            "lease_id": lease["id"], "coverage_start": start,
            "coverage_provenance_sha256": _sha(provenance.encode()),
            "coverage_proof_path": str(Path(coverage["proof_path"]).resolve()),
            "coverage_proof_sha256": coverage["proof_sha256"],
            "lease_artifact": lease_artifact, "authority_artifact": authority_artifact,
            "obligation_artifacts": obligation_artifacts,
            "archives": {key: {"path": str(Path(archives[key]["path"]).resolve()),
                               "sha256": archives[key]["sha256"]}
                         for key in ("frontend", "worker")}}


def _fsync_parent_directory(path: Path, *, platform_name: str | None = None) -> None:
    # Windows has no portable directory descriptor/fsync. Its file fsync and
    # no-overwrite hard-link publication remain mandatory.
    platform_name = os.name if platform_name is None else platform_name
    if platform_name == "nt":
        return
    if platform_name != "posix":
        raise OSError("unsupported platform for transition durability")
    parent = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def _atomic_new(path: Path, data: bytes, *, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise ValueError("transition artifact already exists")
    fd, temporary = tempfile.mkstemp(prefix=".transition-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        _fsync_parent_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def inspect(*, bank_config_file: Path, legacy_frontend_state_dir: Path,
            legacy_worker_state_dir: Path, native_state_dir: Path,
            new_frontend_state_dir: Path, native_authority_dir: Path,
            operator_evidence: Path, source_root: Path) -> dict:
    config = _read_json(bank_config_file)
    bank = Path(config.get("state_db", ""))
    native_state_dir = native_state_dir.resolve()
    new_frontend_state_dir = new_frontend_state_dir.resolve()
    native_authority_dir = native_authority_dir.resolve()
    if (config.get("mode") != "delegated" or not bank.is_absolute()
            or bank.resolve().parent != native_state_dir
            or new_frontend_state_dir == native_state_dir
            or new_frontend_state_dir in native_state_dir.parents
            or new_frontend_state_dir in {legacy_frontend_state_dir.resolve(),
                                          legacy_worker_state_dir.resolve()}
            or native_authority_dir == native_state_dir
            or native_authority_dir in native_state_dir.parents):
        raise ValueError("native state/config authority paths mismatch")
    if new_frontend_state_dir.exists() and (
            not new_frontend_state_dir.is_dir() or any(new_frontend_state_dir.iterdir())):
        raise ValueError("new frontend input state must be empty")
    if any((native_state_dir / name).exists() for name in
           ("frontend-chat.sqlite3", "dispute-workflow.sqlite3", "gloria-workflow.sqlite3")):
        raise ValueError("old application state cannot be selected as native state")
    source = _source(source_root)
    ledger = _ledger(bank, legacy=True)
    proof = _proof(operator_evidence, bank_path=bank, source=source, ledger=ledger,
                   frontend_dir=legacy_frontend_state_dir,
                   worker_dir=legacy_worker_state_dir)
    if config.get("sandbox_report_coverage_start") != proof["coverage_start"]:
        raise ValueError("configured coverage does not match reviewed proof")
    if config.get("ledger_continuity_approved") is not True:
        raise ValueError("private ledger continuity approval absent")
    pin = native_state_dir / "dispute-bank-generation.json"
    if pin.exists() or (native_state_dir / "gloria-bank-generation.json").exists():
        raise ValueError("prior generation pin requires separate recovery review")
    return {"schema": SCHEMA, "bank_path": str(bank.resolve()),
            "native_state_dir": str(native_state_dir),
            "new_frontend_state_dir": str(new_frontend_state_dir),
            "native_authority_dir": str(native_authority_dir),
            "source": source, "legacy_ledger": ledger, "operator_proof": proof,
            "bank_config_sha256": _file_hash(bank_config_file)}


def plan(*, output: Path, **kwargs) -> dict:
    result = inspect(**kwargs)
    _atomic_new(output, _json(result))
    return result


def _archive_bank(db: sqlite3.Connection, path: Path) -> str:
    if path.exists() or path.is_symlink():
        raise ValueError("legacy bank archive already exists")
    fd, temporary = tempfile.mkstemp(prefix=".legacy-bank-", suffix=".sqlite3", dir=path.parent)
    os.close(fd)
    try:
        target = sqlite3.connect(temporary)
        try:
            db.backup(target)
        finally:
            target.close()
        if _ledger(Path(temporary), legacy=True) != _ledger(Path(db.execute("PRAGMA database_list").fetchone()[2]), legacy=True):
            raise ValueError("bank backup not equivalent")
        os.chmod(temporary, 0o600)
        # Windows requires a writable descriptor for FlushFileBuffers/fsync.
        # This is our completed private backup tempfile; opening r+b does not
        # rewrite the SQLite snapshot before no-overwrite publication.
        with open(temporary, "r+b") as stream:
            os.fsync(stream.fileno())
        os.link(temporary, path)
        # The archive name must be durable before the adoption transaction.
        # A sync failure leaves the original ledger untouched for review.
        _fsync_parent_directory(path.parent)
        return _file_hash(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def apply(*, plan_file: Path, bank_config_file: Path, operator_evidence: Path,
          receipt: Path, native_reader_group: int | None = None) -> dict:
    planned = _read_json(plan_file)
    current = inspect(bank_config_file=bank_config_file,
        legacy_frontend_state_dir=Path(_read_json(operator_evidence)["archives"]["frontend"]["original_dir"]),
        legacy_worker_state_dir=Path(_read_json(operator_evidence)["archives"]["worker"]["original_dir"]),
        native_state_dir=Path(planned["native_state_dir"]),
        new_frontend_state_dir=Path(planned["new_frontend_state_dir"]),
        native_authority_dir=Path(planned["native_authority_dir"]),
        operator_evidence=operator_evidence, source_root=Path(planned["source"]["root"]))
    if current != planned or receipt.exists() or receipt.is_symlink():
        raise ValueError("transition plan changed or receipt exists")
    if native_reader_group is not None and (os.name != "posix" or type(native_reader_group) is not int
                                            or native_reader_group < 1):
        raise ValueError("native reader group requires POSIX gid")
    bank_path = Path(planned["bank_path"])
    archive = bank_path.parent / "legacy-bank-before-native.sqlite3"
    # Preserve the original ledger before the schema transaction. A failed
    # transition leaves this archive for explicit recovery; it never restores it.
    with sqlite3.connect(bank_path, timeout=3) as source_db:
        archive_hash = _archive_bank(source_db, archive)
    if _ledger(archive, legacy=True) != planned["legacy_ledger"]:
        raise ValueError("bank changed before archive")
    with sqlite3.connect(bank_path, timeout=3, isolation_level=None) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            if _ledger(bank_path, legacy=True) != planned["legacy_ledger"]:
                raise ValueError("bank changed before adoption")
            for statement in ADDITIVE_SQL:
                db.execute(statement)
            generation = secrets.token_hex(32)
            db.execute("INSERT INTO sandbox_ledger_identity VALUES (1,?)", (generation,))
            db.execute("INSERT INTO sandbox_coverage VALUES (1,?,?,?,?)",
                       (generation, planned["operator_proof"]["coverage_start"],
                        planned["operator_proof"]["coverage_provenance_sha256"], int(time.time())))
            db.commit()
        except BaseException:
            db.rollback()
            raise
    after = _ledger(bank_path, legacy=False)
    if after["generation"] != generation or after["tables"] != planned["legacy_ledger"]["tables"]:
        raise ValueError("post-adoption ledger mismatch")
    result = {"schema": SCHEMA, "plan_sha256": _file_hash(plan_file),
              "source": planned["source"], "bank_path": planned["bank_path"],
              "bank_config_sha256": planned["bank_config_sha256"],
              "operator_proof": planned["operator_proof"],
              "legacy_ledger": planned["legacy_ledger"], "archive_path": str(archive),
              "archive_sha256": archive_hash, "generation": generation,
              "adopted_schema_sha256": after["schema_sha256"],
              "native_state_dir": planned["native_state_dir"],
              "new_frontend_state_dir": planned["new_frontend_state_dir"],
              "native_authority_dir": planned["native_authority_dir"],
              "native_reader_group": native_reader_group}
    _atomic_new(receipt, _json(result))
    verify(receipt=receipt, bank_config_file=bank_config_file,
           source_root=Path(planned["source"]["root"]),
           native_state_dir=Path(planned["native_state_dir"]), require_pin=False)
    pin = bank_path.parent / "dispute-bank-generation.json"
    _atomic_new(pin, _json({"schema": "dispute-bank-generation/v1",
                           "ledger_file": bank_path.name, "ledger_generation": generation}))
    return result


def verify(*, receipt: Path, bank_config_file: Path, source_root: Path,
           native_state_dir: Path, require_pin=True) -> dict:
    saved = _read_json(receipt)
    if saved.get("schema") != SCHEMA or saved.get("native_state_dir") != str(native_state_dir.resolve()):
        raise ValueError("transition receipt or native state mismatch")
    if _source(source_root) != saved.get("source") or _file_hash(bank_config_file) != saved.get("bank_config_sha256"):
        raise ValueError("source or private bank config changed")
    bank_path = Path(saved["bank_path"])
    if bank_path.resolve().parent != native_state_dir.resolve():
        raise ValueError("retained ledger path changed")
    proof = saved.get("operator_proof", {})
    if _file_hash(Path(proof["path"])) != proof.get("sha256"):
        raise ValueError("operator evidence changed")
    if _file_hash(Path(proof["coverage_proof_path"])) != proof.get("coverage_proof_sha256"):
        raise ValueError("coverage proof changed")
    for artifact in (proof["lease_artifact"], proof["authority_artifact"],
                     *proof["obligation_artifacts"]):
        if _file_hash(Path(artifact["path"])) != artifact["sha256"]:
            raise ValueError("old authority or obligation proof changed")
    for artifact in proof["archives"].values():
        if _file_hash(Path(artifact["path"])) != artifact["sha256"]:
            raise ValueError("old state archive changed")
    if _file_hash(Path(saved["archive_path"])) != saved.get("archive_sha256"):
        raise ValueError("legacy bank archive changed")
    if _ledger(Path(saved["archive_path"]), legacy=True) != saved.get("legacy_ledger"):
        raise ValueError("legacy bank rows or schema changed")
    # Revocation tombstones and bound sessions must remain in the active ledger.
    # Expired replay/capability rows may be pruned only after the private archive
    # has retained their original bytes.
    with (contextlib.closing(_connect_ro(Path(saved["archive_path"]))) as old, old,
          contextlib.closing(_connect_ro(bank_path)) as active, active):
        for table in ("revoked", "sessions"):
            retained = set(old.execute("SELECT * FROM " + table))
            present = set(active.execute("SELECT * FROM " + table))
            if not retained.issubset(present):
                raise ValueError("old admission content or revocation lost")
        now = int(time.time())
        for table, expiry_index in (("replays", 1), ("capabilities", 3)):
            active_rows = {row[0]: row for row in active.execute("SELECT * FROM " + table)}
            for original in old.execute("SELECT * FROM " + table):
                present = active_rows.get(original[0])
                if present is not None and present != original:
                    raise ValueError("old replay or capability content changed")
                if present is None and original[expiry_index] > now:
                    raise ValueError("live old replay or capability lost")
    current = _ledger(bank_path, legacy=False)
    if (current["generation"] != saved.get("generation")
            or current["schema_sha256"] != saved.get("adopted_schema_sha256")
            or current["coverage"][:3] != [saved["generation"],
                saved["operator_proof"]["coverage_start"],
                saved["operator_proof"]["coverage_provenance_sha256"]]):
        raise ValueError("adopted generation, schema or coverage changed")
    if require_pin:
        pin = _read_json(native_state_dir / "dispute-bank-generation.json")
        if pin != {"schema": "dispute-bank-generation/v1", "ledger_file": bank_path.name,
                   "ledger_generation": saved["generation"]}:
            raise ValueError("retained generation pin changed")
    return saved


def _synthetic_origin(source_root: Path | None, data_dir: Path) -> tuple[str, str]:
    candidates = []
    if source_root is not None:
        candidates.append(Path(source_root) / "QUALIFICATION_SYNTHETIC.json")
    candidates.append(Path(data_dir) / "QUALIFICATION_SYNTHETIC.json")
    for path in candidates:
        if path.is_file() and not path.is_symlink():
            payload = _read_json(path)
            if payload.get("synthetic") is True and isinstance(payload.get("origin"), str):
                return str(path.resolve()), _file_hash(path)
    raise ValueError("new native state requires authored synthetic source provenance")


def preflight_unreceipted(bank_path: Path, native_state_dir: Path, *,
                          source_root: Path | None, data_dir: Path) -> dict:
    """Read-only provenance fence before a fresh synthetic StateStore."""
    native_state_dir = native_state_dir.resolve()
    bank_path = Path(bank_path)
    if bank_path.is_symlink():
        raise ValueError("bank ledger symlink requires review")
    bank_path = bank_path.resolve()
    for name in (*RETAINED_APP_FILES, "dispute-bank-generation.json",
                 "gloria-bank-generation.json", "native-fresh-origin.json",
                 "legacy-bank-before-native.sqlite3"):
        candidate = native_state_dir / name
        if candidate.is_symlink() or candidate.exists() and not candidate.is_file():
            raise ValueError("retained binding is symlink or nonregular")
    source_path, source_sha = _synthetic_origin(source_root, data_dir)
    if (native_state_dir / "legacy-bank-before-native.sqlite3").exists():
        raise ValueError("retained adoption requires transition receipt")
    marker_path = native_state_dir / "native-fresh-origin.json"
    pin = native_state_dir / "dispute-bank-generation.json"
    legacy_pin = native_state_dir / "gloria-bank-generation.json"
    if legacy_pin.exists() or legacy_pin.is_symlink():
        raise ValueError("legacy generation pin requires reviewed transition")
    if not bank_path.exists():
        if pin.exists() or marker_path.exists() or any((native_state_dir / name).exists()
                                                        for name in RETAINED_APP_FILES):
            raise ValueError("missing ledger beside prior application state")
        return {"new": True, "source_path": source_path, "source_sha256": source_sha}
    with contextlib.closing(_connect_ro(bank_path)) as db, db:
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if not tables:
            raise ValueError("existing ledger file without fresh origin requires review")
        if "sandbox_ledger_identity" not in tables:
            raise ValueError("legacy ledger requires transition receipt before StateStore")
        row = db.execute("SELECT generation FROM sandbox_ledger_identity WHERE id=1").fetchall()
        if len(row) != 1 or not isinstance(row[0][0], str) or not re.fullmatch(r"[a-f0-9]{64}", row[0][0]):
            raise ValueError("native ledger identity invalid")
        generation = row[0][0]
        if marker_path.exists() or marker_path.is_symlink():
            if _read_json(marker_path) != {"schema": "dispute-native-fresh-origin/v1",
                "ledger_file": bank_path.name, "ledger_generation": generation,
                "source_path": source_path, "source_sha256": source_sha}:
                raise ValueError("fresh origin provenance changed")
            saved = _read_json(pin)
            if saved != {"schema": "dispute-bank-generation/v1", "ledger_file": bank_path.name,
                         "ledger_generation": generation}:
                raise ValueError("fresh ledger pin changed")
            return {"new": False, "source_path": source_path, "source_sha256": source_sha}
        # Match the bank_read guarded table and retained-file inventory before
        # Service/StateStore can add schema. Even an empty existing DB with an
        # identity but no fresh-origin marker is ambiguous after lost adoption
        # artifacts and therefore cannot be claimed as newly authored.
        populated = [table for table in sorted(tables & GUARDED_BANK_TABLES)
                     if db.execute("SELECT 1 FROM " + table + " LIMIT 1").fetchone()]
        retained = [name for name in RETAINED_APP_FILES if (native_state_dir / name).exists()]
        if populated or retained:
            raise ValueError("populated retained state without fresh origin requires transition receipt")
        raise ValueError("identity without fresh origin requires transition receipt")


def publish_fresh_origin(state: Path, ledger_file: str, generation: str, preflight: dict) -> None:
    if not preflight["new"]:
        return
    _atomic_new(state / "native-fresh-origin.json", _json({
        "schema": "dispute-native-fresh-origin/v1", "ledger_file": ledger_file,
        "ledger_generation": generation, "source_path": preflight["source_path"],
        "source_sha256": preflight["source_sha256"]}))
