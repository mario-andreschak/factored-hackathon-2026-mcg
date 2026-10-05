"""Fresh fictional Savia RC using project banking service and generic FLUJO language.

No shared bank configuration, ledger, flow or worker is modified. Bank/provider
simulation and this in-process MCP service boundary are explicit in the receipt.
"""
from __future__ import annotations

import argparse
from dataclasses import fields
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

_OBSERVATION_LOCK = threading.Lock()


def observe(root, record):
    record = {"observed_at": datetime.now().astimezone().isoformat(), **record}
    with _OBSERVATION_LOCK, (root / "observations.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def prepare(root: Path) -> None:
    from scripts.qualify_dispute_app import build_fixture, Fixture
    fixture = build_fixture(root)
    values = {field.name: getattr(fixture, field.name) for field in fields(Fixture)}
    for name, value in list(values.items()):
        if isinstance(value, Path):
            values[name] = str(value)
        elif isinstance(value, datetime):
            values[name] = value.isoformat()
        elif isinstance(value, bytes):
            values[name] = value.hex()
    (root / "fixture.json").write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "fixture.json").chmod(0o600)
    print(json.dumps({"prepared": True, "synthetic": True, "private_binding": str(root / "fixture.json")}))


def application(root: Path, *, port: int, base_url: str, model_id: str,
                provider: str = "flujo", provider_key: str | None = None):
    from scripts.qualify_dispute_app import Fixture, application_source_hashes
    from banking_mcp.config import Config
    from banking_mcp.service import Service
    from frontend.server.config import Settings
    from frontend.server.app import create_app
    from dispute_workflow.action_host import BankingActionHost
    from dispute_workflow.host import DisputeHostFactory
    from dispute_workflow.model import FlujoModel
    values = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    for name in ("root", "source", "data", "rates", "signer"):
        values[name] = Path(values[name])
    values["created_at"] = datetime.fromisoformat(values["created_at"])
    values["identifier_salt"] = bytes.fromhex(values["identifier_salt"])
    fixture = Fixture(**values)
    if fixture.root.resolve() != root or not (fixture.source / "QUALIFICATION_SYNTHETIC.json").is_file():
        raise ValueError("exact generated fictional fixture required")
    for name, digest in fixture.source_hashes.items():
        if hashlib.sha256((fixture.source / name).read_bytes()).hexdigest() != digest:
            raise ValueError("fictional source changed; use a fresh instance")
    state = root / "instance"
    coverage = int(fixture.created_at.timestamp()) - 172800
    bank = Service(Config(data_dir=fixture.data, state_db=state / "bank.sqlite3",
        service_token=fixture.service_token, public_keys={"qualification": fixture.public_key},
        principal_customers=fixture.subject_customers, sandbox_report_coverage_start=coverage,
        event_rates_file=fixture.rates, event_rates_sha256=fixture.rates_sha256,
        ledger_continuity_approved=True))
    class ObservedLanguage(FlujoModel):
        async def __call__(self, stage, system, user):
            try:
                return await super().__call__(stage, system, user)
            finally:
                # The parent appends synchronously before returning/raising;
                # no await separates that append from this observer.
                for record in self.observations[-1:]:
                    observe(root, {"kind": "model", **record})

    class ObservedFactory(DisputeHostFactory):
        def __call__(self, *args, **kwargs):
            workflow = super().__call__(*args, **kwargs)
            # Native CLI completion startup needs the same explicit budget as
            # the language transport; initial15s attempts timed out before
            # the observed33-37s completions returned.
            workflow.adapters.timeout_seconds = 90 if provider == "flujo" else 30
            original = workflow.bank.read
            async def read(name, arguments):
                started, status = time.monotonic(), "error"
                try:
                    result = await original(name, arguments)
                    status = result.get("status", "unknown")
                    return result
                finally:
                    observe(root, {"kind": "bank_read", "operation": name, "status": status,
                                   "latency_ms": round((time.monotonic()-started)*1000)})
            workflow.bank.read = read
            return workflow

    for name in ("prepare", "confirm", "receipt", "handoff"):
        original = getattr(bank.actions, name)
        def action(*args, _original=original, _name=name, **kwargs):
            started, status = time.monotonic(), "error"
            try:
                result = _original(*args, **kwargs)
                status = "ok"
                return result
            finally:
                observe(root, {"kind": "bank_action", "operation": _name, "status": status,
                               "latency_ms": round((time.monotonic()-started)*1000)})
        setattr(bank.actions, name, action)
    if provider == "openrouter":
        language = ObservedLanguage("https://openrouter.ai", "model-provider-adapter", provider_key, timeout=30)
        # Reuse the bounded plain completion parser; explicit separate provider
        # mode never masquerades as FLUJO/native flow execution.
        language.base_url, language.model_id = "https://openrouter.ai/api", model_id
    else:
        language = ObservedLanguage(base_url, model_id, timeout=90)
    factory = ObservedFactory(language, state / "dispute-workflow.sqlite3", bank_service=bank,
                                source_root=fixture.source)
    # Authored fictional prior coverage, never 24h of observed bank operation.
    bank.store.attest_sandbox_coverage(coverage, "synthetic:joined-dispute-generated-ledger")
    settings = Settings(data_dir=fixture.data, state_dir=state, static_dir=ROOT / "frontend/dist",
        demo_code=fixture.demo_code, profiles=fixture.profiles, public_origin=f"http://127.0.0.1:{port}",
        chat={"mode": "dispute-host/v1", "base_url": base_url, "model": "flow-Dispute",
              "execution_token": fixture.execution_token,
              "frontend_signing_key_file": str(fixture.signer), "frontend_kid": "qualification",
              "frontend_issuer": "qualification", "frontend_audience": "flujo-banking-ingress",
              "principal_customers": fixture.subject_customers, "action_enabled": True,
              "ledger_generation": factory.ledger_generation})
    app = create_app(settings, dispute_factory=factory,
        bank_backend=BankingActionHost(bank, factory.store, source_root=fixture.source))
    receipt = {"schema": "savia-fictional-rc-runtime/v1", "url": settings.public_origin,
               "fixture": "new generated current-date fiction", "bank": "shipped MCP Service in process",
               "language": {"url": language.base_url, "model": model_id, "provider": provider,
                            "route": "generic completion" if provider == "flujo" else "explicit direct OpenRouter completion"},
               "simulated_intake": True, "real_bank_actions": False, "native_flow_execution": False,
               "source_snapshot": "active local source; freeze at integration checkpoint",
               "application_sources": application_source_hashes(ROOT),
               "launcher_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (root / "runtime.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({"url": receipt["url"], "language": receipt["language"],
                      "source_files": len(receipt["application_sources"])}))
    return app, bank


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", required=True, type=Path)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--port", type=int, default=43900)
    parser.add_argument("--flujo-url", default="http://localhost:43420")
    parser.add_argument("--model", default="model-GPT-6 Luna")
    parser.add_argument("--provider", choices=("flujo", "openrouter"), default="flujo")
    parser.add_argument("--provider-env", type=Path, default=ROOT / "avatar/openrouter.env")
    args = parser.parse_args()
    root = args.private_dir.resolve()
    if not 1024 < args.port < 65536:
        parser.error("loopback service port required")
    if args.prepare:
        prepare(root)
        return
    import httpx
    key = None
    if args.provider == "openrouter":
        import os
        values = {}
        for line in args.provider_env.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                values[name.strip()] = value.strip().strip('"').strip("'")
        key = os.environ.get("OPENROUTER_API_KEY") or values.get("OPENROUTER_API_KEY")
        if not key:
            raise ValueError("existing authorized private provider key required")
        if args.model.startswith("model-"):
            args.model = values.get("OPENROUTER_CHAT_MODEL", "google/gemini-3.1-flash-lite")
        response = httpx.get("https://openrouter.ai/api/v1/models", timeout=10)
    else:
        response = httpx.get(args.flujo_url.rstrip("/") + "/v1/models", timeout=10, trust_env=False)
    response.raise_for_status()
    if args.model not in {item.get("id") for item in response.json().get("data", [])}:
        raise ValueError("configured actual language model is unavailable")
    app, bank = application(root, port=args.port, base_url=args.flujo_url, model_id=args.model,
                            provider=args.provider, provider_key=key)
    try:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
    finally:
        bank.close()


if __name__ == "__main__":
    main()
