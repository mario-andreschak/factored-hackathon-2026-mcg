"""Savia Pro - the local review record.

What this is: an append-only file of review requests raised from the portal,
each carrying the transaction facts exactly as the serving database returned
them, plus a digest over those facts so a reviewer can tell whether the row
changed afterwards.

What this is not, and the wording in the product says so on every surface: it
is not a dispute, not a chargeback, not a refund, not a transfer to an agent,
and it promises no response time. Nothing here reaches a bank.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any

from .config import STATE_DIR

LEDGER = STATE_DIR / "reviews.jsonl"

REASONS = {"unrecognised_charge", "duplicate_suspicion", "amount_wrong",
           "service_not_received", "card_lost_or_stolen", "other"}


def _digest(facts: dict[str, Any]) -> str:
    canonical = json.dumps(facts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def create(*, profile_slug: str, reason: str, answers: dict[str, Any], note: str,
           facts: dict[str, Any], build_id: str, urgent: bool) -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if reason not in REASONS:
        reason = "other"

    # A lost or stolen card is a security matter and outranks whatever else the
    # form said, including the questionnaire, which is skipped entirely.
    security = urgent or reason == "card_lost_or_stolen"

    record = {
        "id": "REV-" + secrets.token_hex(5).upper(),
        "schema": "savia-pro/local-review/v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "profile": profile_slug,
        "reason": "security_concern" if security else reason,
        "priority": "security" if security else "standard",
        "customer_answers": {k: v for k, v in (answers or {}).items() if v is not None},
        "customer_note": (note or "")[:1200],
        "verified_facts": facts,
        "evidence": {
            "source": "serving_snapshot",
            "build_id": build_id,
            "facts_sha256": _digest(facts),
        },
        "questions_skipped": bool(security),
        "bank_action_taken": False,
        "dispute_submitted": False,
        "chargeback_requested": False,
        "refund_issued": False,
        "agent_transfer": False,
        "response_deadline_promised": False,
        "local_only": True,
        "next_step": "Local review record only. No bank decision and no response time are promised.",
    }
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return record


def listing(profile_slug: str, limit: int = 25) -> list[dict[str, Any]]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("profile") == profile_slug:
            out.append(record)
    return list(reversed(out))[:limit]
