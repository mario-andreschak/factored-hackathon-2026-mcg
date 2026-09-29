"""Structured operator handoffs using FLUJO's existing persisted ticket store.

This module does not authenticate a caller, create tickets, or submit disputes.
The host supplies context and bank tool output after authorization/ownership
checks. A model-authored message is never a source of verified banking facts.
The receipt check consumes the actual tool success and ticket-service readback.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping

SCHEMA = "banking-local-handoff/v1"
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
SECRET = re.compile(r"\bBearer\s+\S+|\b(?:xox[baprs]-|xapp-|sk-|ghp_|github_pat_)\S+|"
                    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", re.I)
REASONS = {"requested_human", "security_concern", "unresolved_charge", "missing_evidence", "unsupported_request"}
FACT_FIELDS = ("transaction_reference", "transaction_date", "process_date", "amount", "currency", "status",
               "merchant", "transaction_type", "channel", "product")


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or SECRET.search(value):
        raise ValueError("invalid_handoff_input")
    return value.strip()


@dataclass(frozen=True)
class HandoffContext:
    """Host-owned correlation, NOT an identity proof. Customer is never published."""
    customer_id: str
    conversation_id: str
    flow_id: str

    def __post_init__(self):
        _text(self.customer_id, 128)
        if not all(SAFE_ID.fullmatch(v) for v in (self.conversation_id, self.flow_id)):
            raise ValueError("invalid_handoff_context")


@dataclass(frozen=True)
class TransactionEvidence:
    context: HandoffContext
    facts: tuple[tuple[str, str | None], ...]
    snapshot: str
    freshness: str

    @classmethod
    def from_bank_result(cls, context: HandoffContext, result: Mapping) -> TransactionEvidence:
        """Use ONLY host-observed get_my_transaction output, never model prose.

        Shape validation protects the handoff; authorization remains the bank's.
        Copy the allowlisted facts so subsequent mutation cannot change evidence.
        """
        if not isinstance(result, Mapping) or result.get("read_only") is not True or "error" in result:
            raise ValueError("invalid_bank_evidence")
        transaction = result.get("transaction")
        if not isinstance(transaction, Mapping) or set(transaction) != set(FACT_FIELDS):
            raise ValueError("invalid_bank_evidence")
        values: dict[str, str | None] = {}
        for key in FACT_FIELDS:
            value = transaction[key]
            if key == "merchant" and value is None:
                values[key] = None
            else:
                values[key] = _text(value, 160)
        if not re.fullmatch(r"txn_[a-f0-9]{12}", values["transaction_reference"] or ""):
            raise ValueError("invalid_bank_evidence")
        try:
            amount = Decimal(values["amount"])
            if not amount.is_finite():
                raise ValueError("amount")
            datetime.fromisoformat(values["transaction_date"])
            date.fromisoformat(values["process_date"])
        except (ValueError, TypeError, InvalidOperation):
            raise ValueError("invalid_bank_evidence") from None
        if values["currency"] not in {"MXN", "COP", "ARS", "USD"}:
            raise ValueError("invalid_bank_evidence")
        if values["status"] not in {"Approved", "Declined", "Pending", "Reversed"}:
            raise ValueError("invalid_bank_evidence")
        snapshot = _text(result.get("snapshot"), 96)
        freshness = result.get("freshness")
        if freshness not in {"derived_snapshot", "verified_against_pinned_source"}:
            raise ValueError("invalid_bank_evidence")
        return cls(context, tuple(values.items()), snapshot, freshness)


@dataclass(frozen=True)
class PreparedHandoff:
    context: HandoffContext
    message: str
    language: str

    def tool_arguments(self) -> dict:
        return {"message": self.message, "title": "Banking inquiry: local human review",
                "labels": "banking,local-handoff," + self.language,
                "conversation_id": self.context.conversation_id, "flow_id": self.context.flow_id}


def prepare_handoff(context: HandoffContext, *, request: str, reason: str, language: str,
                    evidence: TransactionEvidence | None = None,
                    unresolved_questions: tuple[str, ...] = ()) -> PreparedHandoff:
    """Build an exact expected envelope for operator acceptance/readback.

    Security requests may escalate without a transaction. Never delay urgent
    human review just to collect banking facts. No free-text action claims exist.
    """
    if language not in {"es", "pt"} or reason not in REASONS or len(unresolved_questions) > 4:
        raise ValueError("invalid_handoff_input")
    if evidence is not None and evidence.context != context:
        raise ValueError("foreign_handoff_evidence")
    envelope = {"schema": SCHEMA, "local_only": True, "language": language,
                "reason": reason, "customer_request": _text(request, 600),
                "verified_facts": dict(evidence.facts) if evidence else {},
                "evidence": {"tool": "get_my_transaction", "snapshot": evidence.snapshot,
                             "freshness": evidence.freshness} if evidence else {},
                "actions_taken": ["read_only_transaction_lookup"] if evidence else [],
                "unresolved_questions": [_text(q, 200) for q in unresolved_questions],
                "bank_action_taken": False, "dispute_submitted": False,
                "next_step": "Local human review; no bank decision or response deadline promised."}
    message = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    if len(message) > 4000:
        raise ValueError("invalid_handoff_input")
    return PreparedHandoff(context, message, language)


def _json_object(text: object) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_field")
            result[key] = value
        return result
    try:
        result = json.loads(text, object_pairs_hook=pairs)
        if not isinstance(result, dict):
            raise ValueError("shape")
        return result
    except (ValueError, TypeError):
        raise ValueError("unverified_handoff_receipt") from None


def verify_ticket_receipt(expected: PreparedHandoff, tool_receipt: Mapping,
                          persisted_ticket: Mapping | None) -> dict:
    """Check actual create_ticket_for_human success against ticketService readback.

    Pass the parsed MCP success block and the result of local getTicket(id) (or
    its private /api/tickets/:id endpoint). A receipt alone is insufficient.
    Neither this helper nor that local endpoint authorizes customer access.
    """
    if not isinstance(tool_receipt, Mapping) or not isinstance(persisted_ticket, Mapping):
        raise ValueError("unverified_handoff_receipt")
    ticket_id = tool_receipt.get("id")
    if (tool_receipt.get("created") is not True or not isinstance(ticket_id, str)
            or not SAFE_ID.fullmatch(ticket_id) or "error" in tool_receipt
            or persisted_ticket.get("id") != ticket_id
            or persisted_ticket.get("conversationId") != expected.context.conversation_id
            or persisted_ticket.get("flowId") != expected.context.flow_id
            or persisted_ticket.get("status") not in {"open", "done"}
            or _json_object(persisted_ticket.get("message")) != _json_object(expected.message)):
        raise ValueError("unverified_handoff_receipt")
    return {"ticket_id": ticket_id, "persisted": True, "readback_verified": True,
            "local_only": True, "bank_action_taken": False, "dispute_submitted": False}
