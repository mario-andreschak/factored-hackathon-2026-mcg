"""Run synthetic development turns through real configured FLUJO model stages.

Bank tools below are deterministic synthetic fixtures, not a deployed bank. No
action port exists and no customer records, credentials or restricted data enter
the report. This evidence is intentionally separate from saved graph activation.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid
import subprocess
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gloria_workflow.model import FlujoModel
from gloria_workflow.prompts import StageAdapters
from gloria_workflow.runtime import Workflow
from gloria_workflow.state import ConversationStore


class SyntheticBank:
    def __init__(self, now):
        self.now, self.calls, self.binding = now, [], None
        self.row = {"transaction_id": "TRX-DEV-QUALIFICATION", "transaction_date": (now.astimezone(ZoneInfo("America/Bogota")) - timedelta(days=1)).date().isoformat() + "T12:00:00", "amount": 27.25, "currency": "USD", "transaction_status": "Approved", "transaction_type": "Purchase", "merchant_name": "Loja Teste", "ref": "1"}

    def bind_context(self, binding):
        self.binding = asdict(binding) if is_dataclass(binding) else dict(binding)

    async def read(self, name, args):
        self.calls.append(name)
        if name == "get_customer_profile":
            return {"status": "ok", "currencies": ["USD"], "products": [{"currency": "USD"}]}
        if name == "search_transactions":
            slots = args.get("slots", {})
            day = self.row["transaction_date"][:10]
            matches = not (slots.get("date_from") and day < slots["date_from"] or slots.get("date_to") and day > slots["date_to"] or slots.get("currency") and slots["currency"] != self.row["currency"] or slots.get("amount") is not None and Decimal(str(slots["amount"])) != Decimal(str(self.row["amount"])) or slots.get("merchant") and slots["merchant"].casefold() not in self.row["merchant_name"].casefold())
            return {"status": "ok", "match_count": int(matches), "candidates": [self.row] if matches else [], "snapshot_hash": "synthetic-qualification", "search_context": {"coverage_complete": True, "snapshot_id": "synthetic-qualification"}}
        if name == "get_transaction":
            return {"status": "ok", "transaction": self.row, "snapshot_hash": "synthetic-qualification", "source_verified": True, "risk_data_complete": True, "risk_signals": {"fraud_score": 0, "amount_usd": 27.25}, "data_quality_flags": []}
        if name == "get_related_complaints":
            read_at = datetime.now(timezone.utc)
            return {"status": "ok", "complaints": [], "duplicate_check": "clear_in_snapshot", "report_window": {"scope": "prototype_sandbox_cases", "window_start": (read_at-timedelta(days=1)).isoformat(), "window_end": read_at.isoformat(), "prior_distinct_verified_count": 0, "coverage_complete": True}}
        if name == "host_action_status":
            return {"status": "ok", "state": "none", "binding_verified": True, "binding": self.binding}
        return {"status": "error", "code": "unsupported_history"}


async def qualify(args):
    root = Path(__file__).resolve().parents[1]
    source_files = list((root / "gloria_workflow").glob("*.py")) + list((root / "resources/prompts").glob("*.yml")) + list((root / "resources/policies").glob("*.md")) + [root / "config/policy_rules.yaml", root / "graph_config_v3.yaml", root / "contracts/state_schema.md", root / "contracts/policy_engine.md", root / "scripts/qualify_gloria.py"]
    def source_hashes():
        return {str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    before_hashes = source_hashes()
    before_commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    token = Path(args.token_file).read_text().strip() if args.token_file else None
    model = FlujoModel(args.base_url, args.model, token, timeout=args.timeout)
    cases = [
        ("es_dispute", "No reconozco una compra de 27.25 USD en Loja Teste ayer.", "CONFIRM_ACTION", "es"),
        ("pt_dispute", "Não reconheço uma compra de 27.25 USD na Loja Teste ontem.", "CONFIRM_ACTION", "pt"),
        ("pt_emergency", "Estão fazendo compras com meu cartão agora mesmo.", "HANDOFF", "pt"),
        ("es_human", "No reconozco una compra, quiero hablar con un asesor.", "HANDOFF", "es"),
    ]
    results = []
    with tempfile.TemporaryDirectory(prefix="gloria-qualification-") as temp:
        for name, message, expected_mode, expected_language in cases:
            now = datetime.now(timezone.utc)
            bank = SyntheticBank(now)
            runner = Workflow(StageAdapters(model, timeout_seconds=args.timeout), bank, ConversationStore(Path(temp)/f"{name}.sqlite3"))
            binding = {"owner": "development-qualifier", "customer_id": "synthetic-only", "session_id": str(uuid.uuid4()), "conversation_id": str(uuid.uuid4()), "expires_at": (now+timedelta(minutes=10)).timestamp()}
            start = time.monotonic()
            state = await runner.run(binding, message)
            mode, language = state["workflow_state"]["policy_decision"]["response_mode"], state["response"]["language"]
            results.append({"case": name, "expected_mode": expected_mode, "mode": mode, "language": language, "pass": mode==expected_mode and language==expected_language, "seconds": round(time.monotonic()-start,3), "rule_ids": state["workflow_state"]["policy_decision"]["rule_ids"], "emotion": state["turn"]["emotional_context"], "intent": state["turn"]["intent"], "slots": state["turn"]["slots"], "safe_fallback": state["runtime"].get("safe_fallback_used",False), "node_errors": state["runtime"]["node_errors"], "bank_reads": bank.calls, "response": state["response"]["message"], "stage_trace": state["trace"]})
            print(json.dumps({k:v for k,v in results[-1].items() if k not in {"response","stage_trace"}}, ensure_ascii=True), flush=True)
    after_hashes = source_hashes()
    unchanged = before_hashes == after_hashes
    report = {"schema": "gloria-development-qualification/v1", "model": args.model, "source_commit": before_commit, "source_dirty": bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip()), "source_hashes": before_hashes, "source_hashes_unchanged": unchanged, "evidence": "real configured language model; synthetic read fixtures; no host actions; graph not installed; no held-out accuracy claim", "cases": results, "usage": model.observations, "cost_usd": None}
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return unchanged and all(r["pass"] for r in results)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url",default="http://127.0.0.1:43420")
    parser.add_argument("--model",required=True)
    parser.add_argument("--token-file")
    parser.add_argument("--timeout",type=int,default=30)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    raise SystemExit(0 if asyncio.run(qualify(args)) else 1)


if __name__ == "__main__":
    main()
