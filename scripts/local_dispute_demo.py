"""Prepare and serve a persistent, explicitly fictional local Dispute demo.

Preparation uses the real fixture pipeline and the bank's supported coverage
API. Serving uses the real native application factory. Neither command installs
a worker or substitutes a model. Private inputs and databases survive shutdown.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SCHEMA = "dispute-persistent-local-demo/v1"
PUBLIC_ORIGIN = "http://127.0.0.1:43900"
STATIC_DIR = Path("/opt/savia/dist")
ACTION_TABLES = ("sandbox_cases", "sandbox_case_receipts", "sandbox_handoffs", "action_pending")


class DemoRejected(ValueError):
    """Bounded startup error; never include private configuration values."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise DemoRejected(code)


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _json(path: Path) -> dict:
    _require(path.is_file() and not path.is_symlink(), "private_input_missing")
    _require(path.stat().st_size < 4 * 1024 * 1024, "private_input_size")
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), "private_input_object")
    return value


def _owned_path(root: Path, relative: str) -> Path:
    _require(isinstance(relative, str) and bool(relative), "private_input_path")
    path = root / relative
    _require(not Path(relative).is_absolute() and path.resolve().is_relative_to(root)
             and not path.is_symlink(), "private_input_path")
    return path


def _coverage(db_path: Path) -> tuple:
    _require(db_path.is_file() and not db_path.is_symlink(), "retained_ledger_missing")
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("""SELECT i.generation,c.generation,c.coverage_start,
            c.provenance_digest,c.attested_at FROM sandbox_ledger_identity i
            JOIN sandbox_coverage c ON c.id=i.id WHERE i.id=1""").fetchone()
    _require(row is not None and row[0] == row[1], "retained_coverage_missing")
    return row


def _settings(frontend: dict):
    from frontend.server.config import Settings
    return Settings(data_dir=Path(frontend["data_dir"]),
        state_dir=Path(frontend["state_dir"]), static_dir=Path(frontend["static_dir"]),
        demo_code=frontend["demo_code"], profiles=frontend["profiles"], chat=frontend["chat"],
        public_origin=frontend["public_origin"], secure_cookie=False)


def _application(settings, bank_config, state, source, bank_config_file, *,
                 native_url, authority_dir, reader_group):
    from scripts.run_dispute import application
    return application(settings, bank_config, state, native_url, Path(authority_dir),
        source_root=source, enable_simulated_intake=True, native_reader_group=reader_group,
        bank_config_file=bank_config_file, application_source_root=ROOT, transition_receipt=None)


@dataclass(frozen=True)
class PreparedDemo:
    root: Path
    manifest: dict
    settings: Any
    bank_config: Any

    @property
    def state(self) -> Path:
        return self.root / "instances" / "interactive"

    @property
    def source(self) -> Path:
        return self.root / "fixture" / "source"

    @property
    def bank_config_file(self) -> Path:
        return self.root / "input-settings" / "bank.json"

    def public_status(self) -> dict:
        return {"schema": SCHEMA, "prepared": True, "synthetic": True,
                "fixture": "authored local fiction; no production data or history",
                "created_at": self.manifest["created_at"], "public_origin": PUBLIC_ORIGIN,
                "simulated_intake_enabled": True,
                "native_execution_verification": "requires actual chat and receipt acceptance",
                "coverage": "authored empty simulator history; not observed bank history"}


def load_demo(root: str | Path) -> PreparedDemo:
    """Validate retained inputs and coverage without creating or repairing state."""
    from banking_mcp.config import load_config
    from scripts.qualify_dispute_app import _tree_hashes

    root = Path(root).resolve()
    manifest = _json(root / "local-demo.json")
    _require(manifest.get("schema") == SCHEMA and manifest.get("synthetic") is True,
             "unowned_demo_directory")
    _require(manifest.get("public_origin") == PUBLIC_ORIGIN, "local_origin_changed")
    _require(not any(path.is_symlink() for directory in (root / "fixture" / "source",
                 root / "fixture" / "data", root / "input-settings")
                 for path in [directory, *directory.rglob("*")]), "retained_input_symlink")
    _require(isinstance(manifest.get("input_sha256"), dict) and bool(manifest["input_sha256"]),
             "private_input_inventory")
    for relative, wanted in manifest["input_sha256"].items():
        path = _owned_path(root, relative)
        _require(path.is_file() and _sha(path) == wanted, "retained_input_changed")
    _require(_tree_hashes(root / "fixture" / "source") == manifest["source_sha256"],
             "retained_source_changed")
    bank = load_config(root / "input-settings" / "bank.json")
    frontend = _json(root / "input-settings" / "frontend.json")
    settings = _settings(frontend)
    state = root / "instances" / "interactive"
    _require(bank.state_db == state / "bank.sqlite3" and bank.data_dir == root / "fixture" / "data"
             and settings.data_dir == bank.data_dir and settings.public_origin == PUBLIC_ORIGIN
             and settings.state_dir == root / "input-settings" / "unused-frontend-state"
             and bank.mode == "delegated" and bank.ledger_continuity_approved is True
             and settings.chat.get("principal_customers") == bank.principal_customers
             and settings.chat.get("action_enabled") is True, "retained_binding_changed")
    expected = manifest["coverage"]
    history = _json(root / "authored-history.json")
    _require(history.get("schema") == "dispute-local-authored-simulator-history/v1"
             and history.get("synthetic") is True
             and history.get("claims_observed_operational_history") is False
             and history.get("created_at") == manifest["created_at"]
             and history.get("coverage_start") == expected["start"]
             and history.get("ledger_generation") == expected["generation"]
             and history.get("source_sha256") == manifest["source_sha256"]
             and history.get("input_sha256") == {key: value for key, value in manifest["input_sha256"].items()
                                                  if key != "authored-history.json"},
             "retained_history_binding_changed")
    row = _coverage(bank.state_db)
    _require(row == (expected["generation"], expected["generation"], expected["start"],
                     expected["provenance_digest"], expected["attested_at"])
             and bank.sandbox_report_coverage_start == expected["start"], "retained_coverage_changed")
    _require(hashlib.sha256(("synthetic:" + _sha(root / "authored-history.json")).encode()).hexdigest()
             == expected["provenance_digest"], "retained_history_changed")
    return PreparedDemo(root, manifest, settings, bank)


def prepare(root: str | Path, *, static_dir: str | Path = STATIC_DIR,
            native_url: str = "http://127.0.0.1:4200",
            authority_dir: str | Path = "/data/native-authority/control",
            reader_group: int | None = 10002) -> PreparedDemo:
    """Create once, or validate this same owned fixture; never reset an occupied root."""
    from banking_mcp.config import Config
    from scripts.qualify_dispute_app import build_fixture, _tree_hashes

    root = Path(root).resolve()
    if (root / "local-demo.json").exists():
        return load_demo(root)
    _require(not root.exists() or root.is_dir() and not any(root.iterdir()), "occupied_demo_directory")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fixture = build_fixture(root / "fixture")
    state = root / "instances" / "interactive"
    state.mkdir(parents=True, mode=0o700)
    created = fixture.created_at.astimezone(timezone.utc)
    coverage_start = int(created.timestamp()) - 172800
    config = Config(data_dir=fixture.data, state_db=state / "bank.sqlite3",
        service_token=fixture.service_token, public_keys={"qualification": fixture.public_key},
        principal_customers=fixture.subject_customers, event_rates_file=fixture.rates,
        event_rates_sha256=fixture.rates_sha256, sandbox_report_coverage_start=coverage_start,
        ledger_continuity_approved=True)
    frontend = {"data_dir": str(fixture.data),
        "state_dir": str(root / "input-settings" / "unused-frontend-state"),
        "static_dir": str(Path(static_dir).resolve()), "demo_code": fixture.demo_code,
        "profiles": fixture.profiles, "public_origin": PUBLIC_ORIGIN,
        "chat": {"base_url": "http://127.0.0.1:4200", "model": "flow-Dispute",
            "execution_token": fixture.execution_token, "frontend_signing_key_file": str(fixture.signer),
            "frontend_kid": "qualification", "frontend_issuer": "qualification",
            "frontend_audience": "flujo-banking-ingress",
            "principal_customers": fixture.subject_customers, "action_enabled": True}}
    _write(root / "input-settings" / "bank.json", _bytes(config.model_dump(mode="json")))
    _write(root / "input-settings" / "frontend.json", _bytes(frontend))
    # A dedicated file lets the human retrieve only the local access code.
    _write(root / "local-access.json", _bytes({"demo_code": fixture.demo_code}))
    # The source-owned factory performs the fresh-state preflight and publishes
    # its real pin/origin BEFORE coverage or any retained admission is created.
    # Constructing the app starts no lifespan, listener, worker or provider call.
    app, bank = _application(_settings(frontend), config, state, fixture.source,
        root / "input-settings" / "bank.json", native_url=native_url,
        authority_dir=authority_dir, reader_group=reader_group)
    store = bank.store
    bank.close()
    del app
    immutable = [root / "input-settings" / "bank.json", root / "input-settings" / "frontend.json",
                 root / "local-access.json", fixture.signer, fixture.rates,
                 root / "fixture" / "private-admission.json", root / "fixture" / "identifier-salt.bin",
                 state / "dispute-bank-generation.json", state / "native-fresh-origin.json"]
    immutable.extend(path for path in fixture.data.rglob("*") if path.is_file())
    input_hashes = {path.relative_to(root).as_posix(): _sha(path) for path in sorted(immutable)}
    with store.connect() as db:
        generation = db.execute("SELECT generation FROM sandbox_ledger_identity WHERE id=1").fetchone()[0]
        _require(all(db.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0
                     for table in ACTION_TABLES), "fixture_ledger_not_empty")
    history = {"schema": "dispute-local-authored-simulator-history/v1", "synthetic": True,
        "claims_observed_operational_history": False, "created_at": created.isoformat(),
        "coverage_start": coverage_start, "authored_reports": [], "owners": sorted(fixture.subject_customers.values()),
        "source_sha256": fixture.source_hashes, "event_rates_sha256": fixture.rates_sha256,
        "ledger_generation": generation, "setup_closed_at": int(time.time()),
        "input_sha256": input_hashes,
        "snapshot_files_sha256": _tree_hashes(fixture.data),
        "setup_gap": "fresh generated fixture to exclusive fresh ledger; no service has started"}
    _write(root / "authored-history.json", _bytes(history))
    provenance = "synthetic:" + _sha(root / "authored-history.json")
    store.attest_sandbox_coverage(coverage_start, provenance)
    row = _coverage(config.state_db)
    manifest = {"schema": SCHEMA, "synthetic": True, "public_origin": PUBLIC_ORIGIN,
        "created_at": created.isoformat(), "source_sha256": fixture.source_hashes,
        "input_sha256": {**input_hashes, "authored-history.json": _sha(root / "authored-history.json")},
        "coverage": {"generation": generation, "start": row[2],
                     "provenance_digest": row[3], "attested_at": row[4]}}
    # Publish last: an interrupted bootstrap stays occupied and is never regenerated.
    _write(root / "local-demo.json", _bytes(manifest))
    return load_demo(root)


def serve(demo: PreparedDemo, *, static_dir: str | Path = STATIC_DIR, port: int = 8082,
          native_url: str = "http://127.0.0.1:4200",
          authority_dir: str | Path = "/data/native-authority/control",
          reader_group: int | None = 10002) -> None:
    """Run the actual admitted app behind the separately owned local proxy."""
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    import uvicorn

    _require(1024 < port < 65536, "local_port_invalid")
    _require(native_url.startswith("http://127.0.0.1:") and native_url.removeprefix(
             "http://127.0.0.1:").isdigit(), "local_native_url_invalid")
    _require(reader_group is None or type(reader_group) is int and reader_group > 0,
             "native_reader_group_invalid")
    static = Path(static_dir).resolve()
    _require((static / "index.html").is_file(), "current_frontend_build_missing")
    app, bank = _application(replace(demo.settings, static_dir=static), demo.bank_config,
        demo.state, demo.source, demo.bank_config_file, native_url=native_url,
        authority_dir=authority_dir, reader_group=reader_group)
    try:
        async def public_status(request):
            return JSONResponse({**demo.public_status(), "server_running": True,
                "frontend_build_present": True}, headers={"Cache-Control": "no-store"})
        # Insert ahead of the SPA catch-all; this exposes no private inputs.
        app.router.routes.insert(0, Route("/local-demo/status", public_status, methods=["GET"]))
        uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")
    finally:
        bank.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "serve", "status"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--static-dir", type=Path, default=STATIC_DIR)
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--native-url", default="http://127.0.0.1:4200")
    parser.add_argument("--public-origin", default=PUBLIC_ORIGIN)
    parser.add_argument("--native-authority-dir", type=Path, default=Path("/data/native-authority/control"))
    parser.add_argument("--native-reader-group", type=int, default=10002)
    args = parser.parse_args(argv)
    try:
        _require(args.public_origin == PUBLIC_ORIGIN, "local_origin_changed")
        demo = prepare(args.root, static_dir=args.static_dir, native_url=args.native_url,
            authority_dir=args.native_authority_dir, reader_group=args.native_reader_group
            ) if args.command == "prepare" else load_demo(args.root)
        if args.command == "serve":
            serve(demo, static_dir=args.static_dir, port=args.port, native_url=args.native_url,
                  authority_dir=args.native_authority_dir, reader_group=args.native_reader_group)
        else:
            print(json.dumps(demo.public_status(), sort_keys=True))
        return 0
    except Exception as exc:
        # Validation errors can carry private inputs; only bounded codes/types escape.
        code = str(exc) if isinstance(exc, DemoRejected) else type(exc).__name__
        print(json.dumps({"schema": SCHEMA, "status": "rejected", "code": code}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
